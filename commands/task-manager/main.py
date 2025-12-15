"""Task Manager Microservice.

HTTP API for managing tasks extracted from transcripts.
Uses the graph-store backend for persistence.

Endpoints:
- GET /tasks - List tasks with filtering
- GET /tasks/<id> - Get a specific task
- POST /tasks - Create a new task
- PUT /tasks/<id> - Update a task
- DELETE /tasks/<id> - Delete a task
- POST /tasks/<id>/complete - Mark task as complete
- POST /tasks/<id>/reopen - Reopen a completed task
- GET /stats - Get task statistics
- GET /context/<id> - Get LLM context for a task (GraphRAG)
"""

import json
import os
import sys
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from zoneinfo import ZoneInfo

import functions_framework
from flask import Request
from google.cloud import storage

# Local timezone (configurable via LOCAL_TIMEZONE env var)
LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "Pacific/Auckland"))

# Storage mode: "graph" (uses graph-store) or "legacy" (direct GCS JSON)
STORAGE_MODE = os.environ.get("STORAGE_MODE", "graph")


def log_structured(severity: str, message: str, **kwargs):
    """Output structured JSON log for Cloud Logging."""
    log_entry = {
        "severity": severity,
        "message": message,
        "component": "task-manager",
        **kwargs
    }
    print(json.dumps(log_entry))


# =============================================================================
# Graph Store Backend (primary)
# =============================================================================

class GraphTaskStore:
    """Task storage using graph-store backend.

    Stores tasks as nodes in the knowledge graph with relationships
    to topics, transcripts, and other entities.
    """

    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        self._client = None
        self._tasks: Optional[Dict[str, Dict]] = None
        self._edges: Optional[List[Dict]] = None

    @property
    def client(self):
        if self._client is None:
            self._client = storage.Client()
        return self._client

    @property
    def bucket(self):
        return self.client.bucket(self.bucket_name)

    def _load_tasks(self) -> Dict[str, Dict]:
        """Load tasks from graph storage."""
        if self._tasks is not None:
            return self._tasks

        self._tasks = {}
        blob = self.bucket.blob("graph/nodes/task.jsonl")

        if blob.exists():
            for line in blob.download_as_text().strip().split("\n"):
                if line:
                    task = json.loads(line)
                    self._tasks[task["@id"]] = task

        return self._tasks

    def _save_tasks(self):
        """Save tasks to graph storage."""
        lines = [json.dumps(t) for t in self._tasks.values()]
        blob = self.bucket.blob("graph/nodes/task.jsonl")
        blob.upload_from_string("\n".join(lines) + "\n" if lines else "", content_type="application/jsonl")

        # Update index
        self._update_index()

    def _update_index(self):
        """Update the type index."""
        index_blob = self.bucket.blob("graph/indexes/by_type.json")
        try:
            existing = json.loads(index_blob.download_as_text()) if index_blob.exists() else {"types": {}}
        except Exception:
            existing = {"types": {}}

        existing["types"]["Task"] = list(self._tasks.keys())
        index_blob.upload_from_string(json.dumps(existing, indent=2), content_type="application/json")

    def _load_edges(self) -> List[Dict]:
        """Load edges related to tasks."""
        if self._edges is not None:
            return self._edges

        self._edges = []
        blob = self.bucket.blob("graph/edges/relationships.jsonl")

        if blob.exists():
            for line in blob.download_as_text().strip().split("\n"):
                if line:
                    edge = json.loads(line)
                    # Only load edges involving tasks
                    if edge.get("from_id", "").startswith("task:") or edge.get("to_id", "").startswith("task:"):
                        self._edges.append(edge)

        return self._edges

    def _save_edges(self):
        """Save edges to graph storage."""
        # Load all edges first
        blob = self.bucket.blob("graph/edges/relationships.jsonl")
        all_edges = {}

        if blob.exists():
            for line in blob.download_as_text().strip().split("\n"):
                if line:
                    edge = json.loads(line)
                    all_edges[edge["@id"]] = edge

        # Update with our edges
        for edge in self._edges:
            all_edges[edge["@id"]] = edge

        lines = [json.dumps(e) for e in all_edges.values()]
        blob.upload_from_string("\n".join(lines) + "\n" if lines else "", content_type="application/jsonl")

    def get_all(self, filters: Optional[Dict] = None, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get all tasks with optional filtering."""
        tasks = list(self._load_tasks().values())

        if filters:
            for key, value in filters.items():
                if key == "topic":
                    # Prefix match for topics
                    tasks = [t for t in tasks if t.get("primary_topic", "").startswith(value)]
                elif key == "assignee":
                    if value.lower() == "unassigned":
                        tasks = [t for t in tasks if not t.get("assignee")]
                    else:
                        tasks = [t for t in tasks if (t.get("assignee") or "").lower() == value.lower()]
                elif key == "search":
                    value_lower = value.lower()
                    tasks = [t for t in tasks if value_lower in t.get("description", "").lower()]
                else:
                    tasks = [t for t in tasks if t.get(key) == value]

        # Sort by created_at descending
        tasks.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return tasks[offset:offset + limit]

    def count(self, filters: Optional[Dict] = None) -> int:
        """Count tasks matching filters."""
        return len(self.get_all(filters, limit=10000))

    def get(self, task_id: str) -> Optional[Dict]:
        """Get a task by ID."""
        # Normalize ID format
        if not task_id.startswith("task:"):
            task_id = f"task:{task_id}"
        return self._load_tasks().get(task_id)

    def create(self, data: Dict) -> Dict:
        """Create a new task."""
        self._load_tasks()

        now = datetime.now(LOCAL_TIMEZONE).isoformat()
        task_id = f"task:{uuid.uuid4().hex[:12]}"

        task = {
            "@type": "Task",
            "@id": task_id,
            "description": data.get("description", ""),
            "status": data.get("status", "pending"),
            "priority": data.get("priority", "medium"),
            "assignee": data.get("assignee"),
            "deadline": data.get("deadline"),
            "primary_topic": data.get("primary_topic", "General"),
            "secondary_topics": data.get("secondary_topics", []),
            "context": data.get("context"),
            "source_transcript_id": data.get("source_transcript_id"),
            "source_transcript_title": data.get("source_transcript_title"),
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "notes": []
        }

        self._tasks[task_id] = task
        self._save_tasks()

        # Create topic edge if topic exists
        self._create_topic_edge(task_id, task.get("primary_topic"))

        return task

    def update(self, task_id: str, data: Dict) -> Dict:
        """Update a task."""
        self._load_tasks()

        if not task_id.startswith("task:"):
            task_id = f"task:{task_id}"

        if task_id not in self._tasks:
            raise KeyError(f"Task not found: {task_id}")

        task = self._tasks[task_id]
        now = datetime.now(LOCAL_TIMEZONE).isoformat()

        # Update allowed fields
        updatable = ["description", "assignee", "deadline", "primary_topic",
                     "secondary_topics", "priority", "context", "status"]
        for field in updatable:
            if field in data:
                task[field] = data[field]

        task["updated_at"] = now
        self._save_tasks()

        return task

    def delete(self, task_id: str) -> bool:
        """Delete a task."""
        self._load_tasks()

        if not task_id.startswith("task:"):
            task_id = f"task:{task_id}"

        if task_id not in self._tasks:
            return False

        del self._tasks[task_id]
        self._save_tasks()

        # Delete associated edges
        self._delete_edges_for_task(task_id)

        return True

    def complete(self, task_id: str) -> Dict:
        """Mark task as complete."""
        return self.update(task_id, {
            "status": "completed",
            "completed_at": datetime.now(LOCAL_TIMEZONE).isoformat()
        })

    def reopen(self, task_id: str) -> Dict:
        """Reopen a completed task."""
        return self.update(task_id, {
            "status": "pending",
            "completed_at": None
        })

    def get_stats(self) -> Dict:
        """Get task statistics."""
        tasks = self.get_all(limit=10000)

        stats = {
            "total_tasks": len(tasks),
            "by_status": {},
            "by_priority": {},
            "by_topic": {},
            "by_assignee": {}
        }

        for task in tasks:
            # By status
            status = task.get("status", "pending")
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

            # By priority
            priority = task.get("priority", "medium")
            stats["by_priority"][priority] = stats["by_priority"].get(priority, 0) + 1

            # By topic
            topic = task.get("primary_topic", "General")
            stats["by_topic"][topic] = stats["by_topic"].get(topic, 0) + 1

            # By assignee
            assignee = task.get("assignee") or "Unassigned"
            stats["by_assignee"][assignee] = stats["by_assignee"].get(assignee, 0) + 1

        return stats

    def _create_topic_edge(self, task_id: str, topic_path: str):
        """Create edge from task to topic if topic exists."""
        if not topic_path:
            return

        topic_id = f"topic:{topic_path.lower().replace('/', '_')}"

        # Check if topic exists
        topic_blob = self.bucket.blob("graph/nodes/topic.jsonl")
        if not topic_blob.exists():
            return

        topic_exists = False
        for line in topic_blob.download_as_text().strip().split("\n"):
            if line:
                topic = json.loads(line)
                if topic.get("@id") == topic_id:
                    topic_exists = True
                    break

        if topic_exists:
            self._load_edges()
            edge = {
                "@id": f"edge:{uuid.uuid4().hex[:12]}",
                "@type": "Edge",
                "from_id": task_id,
                "relation": "hasTopic",
                "to_id": topic_id,
                "created_at": datetime.now(LOCAL_TIMEZONE).isoformat()
            }
            self._edges.append(edge)
            self._save_edges()

    def _delete_edges_for_task(self, task_id: str):
        """Delete all edges connected to a task."""
        self._load_edges()
        self._edges = [
            e for e in self._edges
            if e.get("from_id") != task_id and e.get("to_id") != task_id
        ]
        self._save_edges()

    def get_context(self, task_id: str, depth: int = 2) -> Dict:
        """Get LLM context for a task (subgraph extraction).

        Returns JSON-LD formatted context suitable for LLM reasoning.
        """
        if not task_id.startswith("task:"):
            task_id = f"task:{task_id}"

        task = self.get(task_id)
        if not task:
            return {"error": "Task not found"}

        nodes = {task_id: task}
        edges = []

        # Get related nodes via edges
        self._load_edges()
        for edge in self._edges:
            if edge.get("from_id") == task_id:
                edges.append(edge)
                related_id = edge.get("to_id")
                related = self._get_any_node(related_id)
                if related:
                    nodes[related_id] = related
            elif edge.get("to_id") == task_id:
                edges.append(edge)
                related_id = edge.get("from_id")
                related = self._get_any_node(related_id)
                if related:
                    nodes[related_id] = related

        # Get sibling tasks (same topic)
        if task.get("primary_topic") and depth > 1:
            siblings = self.get_all({"topic": task["primary_topic"]}, limit=5)
            for sibling in siblings:
                if sibling["@id"] != task_id:
                    nodes[sibling["@id"]] = sibling

        return {
            "@context": {
                "@vocab": "https://schema.org/",
                "Task": "https://schema.org/Action",
                "Topic": "https://schema.org/Thing",
                "hasTopic": {"@type": "@id"}
            },
            "@graph": list(nodes.values()),
            "_edges": edges,
            "_meta": {
                "focal_node": task_id,
                "depth": depth,
                "node_count": len(nodes),
                "edge_count": len(edges)
            }
        }

    def _get_any_node(self, node_id: str) -> Optional[Dict]:
        """Get any node by ID (looks in all node files)."""
        # Determine type from ID prefix
        if node_id.startswith("topic:"):
            blob = self.bucket.blob("graph/nodes/topic.jsonl")
        elif node_id.startswith("goal:"):
            blob = self.bucket.blob("graph/nodes/goal.jsonl")
        elif node_id.startswith("project:"):
            blob = self.bucket.blob("graph/nodes/project.jsonl")
        elif node_id.startswith("transcript:"):
            blob = self.bucket.blob("graph/nodes/transcript.jsonl")
        else:
            return None

        if not blob.exists():
            return None

        for line in blob.download_as_text().strip().split("\n"):
            if line:
                node = json.loads(line)
                if node.get("@id") == node_id:
                    return node

        return None


# =============================================================================
# Legacy Store (fallback)
# =============================================================================

class LegacyTaskStore:
    """Legacy task storage using direct GCS JSON file."""

    TASKS_FILE = "managed/tasks.json"

    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        self._client = None
        self._data: Optional[Dict] = None

    @property
    def client(self):
        if self._client is None:
            self._client = storage.Client()
        return self._client

    @property
    def bucket(self):
        return self.client.bucket(self.bucket_name)

    def _load(self) -> Dict:
        if self._data is not None:
            return self._data

        blob = self.bucket.blob(self.TASKS_FILE)
        default = {
            "version": "1.0",
            "tasks": {},
            "indexes": {"by_status": {}, "by_topic": {}, "by_assignee": {}, "by_priority": {}}
        }

        if blob.exists():
            try:
                self._data = json.loads(blob.download_as_text())
            except Exception:
                self._data = default
        else:
            self._data = default

        return self._data

    def _save(self):
        self._data["last_updated"] = datetime.now(LOCAL_TIMEZONE).isoformat()
        blob = self.bucket.blob(self.TASKS_FILE)
        blob.upload_from_string(json.dumps(self._data, indent=2), content_type="application/json")

    def get_all(self, filters: Optional[Dict] = None, limit: int = 100, offset: int = 0) -> List[Dict]:
        data = self._load()
        tasks = []

        for task_id, task in data.get("tasks", {}).items():
            task_with_id = {"@id": task_id, **task}

            if filters:
                skip = False
                for key, value in filters.items():
                    if key == "topic" and not task.get("primary_topic", "").startswith(value):
                        skip = True
                    elif key == "search" and value.lower() not in task.get("description", "").lower():
                        skip = True
                    elif key not in ["topic", "search"] and task.get(key) != value:
                        skip = True
                if skip:
                    continue

            tasks.append(task_with_id)

        tasks.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return tasks[offset:offset + limit]

    def count(self, filters: Optional[Dict] = None) -> int:
        return len(self.get_all(filters, limit=10000))

    def get(self, task_id: str) -> Optional[Dict]:
        data = self._load()
        task = data.get("tasks", {}).get(task_id)
        if task:
            return {"@id": task_id, **task}
        return None

    def create(self, task_data: Dict) -> Dict:
        data = self._load()
        now = datetime.now(LOCAL_TIMEZONE).isoformat()
        task_id = f"task:{uuid.uuid4().hex[:12]}"

        task = {
            "description": task_data.get("description", ""),
            "status": "pending",
            "priority": task_data.get("priority", "medium"),
            "assignee": task_data.get("assignee"),
            "deadline": task_data.get("deadline"),
            "primary_topic": task_data.get("primary_topic", "General"),
            "secondary_topics": task_data.get("secondary_topics", []),
            "context": task_data.get("context"),
            "source_transcript_id": task_data.get("source_transcript_id"),
            "source_transcript_title": task_data.get("source_transcript_title"),
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "notes": []
        }

        data["tasks"][task_id] = task
        self._save()
        return {"@id": task_id, **task}

    def update(self, task_id: str, task_data: Dict) -> Dict:
        data = self._load()
        if task_id not in data.get("tasks", {}):
            raise KeyError(f"Task not found: {task_id}")

        task = data["tasks"][task_id]
        for key in ["description", "assignee", "deadline", "primary_topic", "secondary_topics", "priority", "context", "status"]:
            if key in task_data:
                task[key] = task_data[key]
        task["updated_at"] = datetime.now(LOCAL_TIMEZONE).isoformat()

        self._save()
        return {"@id": task_id, **task}

    def delete(self, task_id: str) -> bool:
        data = self._load()
        if task_id not in data.get("tasks", {}):
            return False
        del data["tasks"][task_id]
        self._save()
        return True

    def complete(self, task_id: str) -> Dict:
        return self.update(task_id, {"status": "completed", "completed_at": datetime.now(LOCAL_TIMEZONE).isoformat()})

    def reopen(self, task_id: str) -> Dict:
        return self.update(task_id, {"status": "pending", "completed_at": None})

    def get_stats(self) -> Dict:
        data = self._load()
        tasks = data.get("tasks", {})
        return {
            "total_tasks": len(tasks),
            "by_status": {},
            "by_priority": {},
            "by_topic": {},
            "by_assignee": {}
        }

    def get_context(self, task_id: str, depth: int = 2) -> Dict:
        task = self.get(task_id)
        if not task:
            return {"error": "Task not found"}
        return {"@graph": [task], "_edges": [], "_meta": {"focal_node": task_id}}


# =============================================================================
# Store Factory
# =============================================================================

def get_store():
    """Get the appropriate task store based on configuration."""
    bucket_name = os.environ.get("GCS_BUCKET")
    if not bucket_name:
        raise ValueError("GCS_BUCKET environment variable not set")

    if STORAGE_MODE == "legacy":
        return LegacyTaskStore(bucket_name)
    return GraphTaskStore(bucket_name)


def parse_json(request: Request) -> dict:
    try:
        return request.get_json(force=True) or {}
    except Exception:
        return {}


def json_response(data: dict, status: int = 200):
    return data, status, {"Content-Type": "application/json"}


# =============================================================================
# HTTP API
# =============================================================================

@functions_framework.http
def task_api(request: Request):
    """Main HTTP API for task management.

    Routes:
    - GET    /              - List tasks
    - GET    /stats         - Get statistics
    - POST   /              - Create task
    - GET    /{id}          - Get task
    - PUT    /{id}          - Update task
    - DELETE /{id}          - Delete task
    - POST   /{id}/complete - Complete task
    - POST   /{id}/reopen   - Reopen task
    - GET    /{id}/context  - Get LLM context (GraphRAG)
    - POST   /import        - Import from consolidated tasks
    """
    try:
        store = get_store()
        path = request.path.strip("/")
        path_parts = path.split("/") if path else []
        method = request.method

        # GET / - List tasks
        if method == "GET" and len(path_parts) == 0:
            filters = {}
            for key in ["status", "priority", "assignee", "topic"]:
                if key in request.args:
                    filters[key] = request.args.get(key)
            if "q" in request.args:
                filters["search"] = request.args.get("q")

            limit = int(request.args.get("limit", 100))
            offset = int(request.args.get("offset", 0))

            tasks = store.get_all(filters if filters else None, limit, offset)
            total = store.count(filters if filters else None)

            return json_response({
                "total": total,
                "count": len(tasks),
                "limit": limit,
                "offset": offset,
                "tasks": tasks
            })

        # GET /stats
        if method == "GET" and path_parts == ["stats"]:
            return json_response(store.get_stats())

        # POST / - Create task
        if method == "POST" and len(path_parts) == 0:
            body = parse_json(request)
            if not body.get("description"):
                return json_response({"error": "description is required"}, 400)

            task = store.create(body)
            log_structured("INFO", f"Created task: {task['@id']}", event="task_created")
            return json_response({"task": task}, 201)

        # POST /import
        if method == "POST" and path_parts == ["import"]:
            return import_tasks(request, store)

        # Routes with task ID
        if len(path_parts) >= 1:
            task_id = path_parts[0]

            # GET /{id}
            if method == "GET" and len(path_parts) == 1:
                task = store.get(task_id)
                if not task:
                    return json_response({"error": "Task not found"}, 404)
                return json_response({"task": task})

            # PUT /{id}
            if method == "PUT" and len(path_parts) == 1:
                body = parse_json(request)
                try:
                    task = store.update(task_id, body)
                    log_structured("INFO", f"Updated task: {task_id}", event="task_updated")
                    return json_response({"task": task})
                except KeyError:
                    return json_response({"error": "Task not found"}, 404)

            # DELETE /{id}
            if method == "DELETE" and len(path_parts) == 1:
                if not store.delete(task_id):
                    return json_response({"error": "Task not found"}, 404)
                log_structured("INFO", f"Deleted task: {task_id}", event="task_deleted")
                return json_response({"success": True, "task_id": task_id})

            # POST /{id}/complete
            if method == "POST" and len(path_parts) == 2 and path_parts[1] == "complete":
                try:
                    task = store.complete(task_id)
                    log_structured("INFO", f"Completed task: {task_id}", event="task_completed")
                    return json_response({"task": task})
                except KeyError:
                    return json_response({"error": "Task not found"}, 404)

            # POST /{id}/reopen
            if method == "POST" and len(path_parts) == 2 and path_parts[1] == "reopen":
                try:
                    task = store.reopen(task_id)
                    log_structured("INFO", f"Reopened task: {task_id}", event="task_reopened")
                    return json_response({"task": task})
                except KeyError:
                    return json_response({"error": "Task not found"}, 404)

            # GET /{id}/context - LLM context (GraphRAG)
            if method == "GET" and len(path_parts) == 2 and path_parts[1] == "context":
                depth = int(request.args.get("depth", 2))
                context = store.get_context(task_id, depth)
                if "error" in context:
                    return json_response(context, 404)
                return json_response(context)

        return json_response({"error": "Not found", "path": request.path}, 404)

    except Exception as e:
        log_structured("ERROR", f"API error: {e}", error=str(e), path=request.path)
        return json_response({"error": str(e)}, 500)


def import_tasks(request: Request, store):
    """Import tasks from consolidated_tasks.json."""
    dry_run = request.args.get("dry_run", "").lower() == "true"

    bucket_name = os.environ.get("GCS_BUCKET")
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    blob = bucket.blob("tasks/consolidated_tasks.json")
    if not blob.exists():
        return json_response({"error": "consolidated_tasks.json not found"}, 404)

    try:
        consolidated = json.loads(blob.download_as_text())
    except Exception as e:
        return json_response({"error": f"Failed to load: {e}"}, 500)

    imported = []
    for task_data in consolidated.get("tasks", []):
        if not dry_run:
            task = store.create(task_data)
            imported.append({"id": task["@id"], "description": task["description"][:50]})
        else:
            imported.append({"description": task_data.get("description", "")[:50]})

    return json_response({
        "dry_run": dry_run,
        "imported_count": len(imported),
        "imported": imported[:20]
    })


@functions_framework.http
def health_check(request):
    """Health check endpoint."""
    return json_response({
        "status": "healthy",
        "service": "task-manager",
        "storage_mode": STORAGE_MODE
    })
