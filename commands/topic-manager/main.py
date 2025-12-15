"""Topic Manager Microservice.

HTTP API for managing topics/taxonomy in the knowledge graph.
Provides hierarchical topic management with operations like merge, move, and tree traversal.

This service uses the graph-store backend for persistence.
"""

import json
import os
import re
from typing import Optional, List, Dict, Any
from datetime import datetime
from zoneinfo import ZoneInfo

import functions_framework
from flask import Request
from google.cloud import storage

# Import graph-store components (deployed as separate service or shared library)
# For now, we include a lightweight client that calls the graph-store API
# or use direct backend access if co-deployed

LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "Pacific/Auckland"))


def log_structured(severity: str, message: str, **kwargs):
    """Output structured JSON log for Cloud Logging."""
    log_entry = {
        "severity": severity,
        "message": message,
        "component": "topic-manager",
        **kwargs
    }
    print(json.dumps(log_entry))


class TopicStore:
    """Topic storage using GCS JSON files.

    For production, this would call the graph-store API.
    This implementation provides direct GCS access for simplicity.
    """

    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        self._client = None
        self._topics: Optional[Dict[str, Dict]] = None

    @property
    def client(self):
        if self._client is None:
            self._client = storage.Client()
        return self._client

    @property
    def bucket(self):
        return self.client.bucket(self.bucket_name)

    def _load_topics(self) -> Dict[str, Dict]:
        """Load topics from graph storage."""
        if self._topics is not None:
            return self._topics

        self._topics = {}

        # Try to load from graph-store format first
        blob = self.bucket.blob("graph/nodes/topic.jsonl")
        if blob.exists():
            for line in blob.download_as_text().strip().split("\n"):
                if line:
                    topic = json.loads(line)
                    self._topics[topic["@id"]] = topic
            return self._topics

        # Fall back to legacy taxonomy format
        blob = self.bucket.blob("topic_taxonomy.json")
        if blob.exists():
            taxonomy = json.loads(blob.download_as_text())
            for topic in taxonomy.get("topics", []):
                path = topic.get("path", "")
                topic_id = f"topic:{path.lower().replace('/', '_')}"
                self._topics[topic_id] = {
                    "@type": "Topic",
                    "@id": topic_id,
                    "name": path.split("/")[-1],
                    "path": path,
                    "description": topic.get("description", ""),
                    "examples": topic.get("examples", [])
                }

        return self._topics

    def _save_topics(self):
        """Save topics to graph storage."""
        lines = [json.dumps(t) for t in self._topics.values()]
        blob = self.bucket.blob("graph/nodes/topic.jsonl")
        blob.upload_from_string("\n".join(lines) + "\n", content_type="application/jsonl")

        # Also update the index
        index_blob = self.bucket.blob("graph/indexes/by_type.json")
        try:
            existing = json.loads(index_blob.download_as_text()) if index_blob.exists() else {"types": {}}
        except Exception:
            existing = {"types": {}}

        existing["types"]["Topic"] = list(self._topics.keys())
        index_blob.upload_from_string(json.dumps(existing, indent=2), content_type="application/json")

    def get_all(self) -> List[Dict]:
        """Get all topics."""
        return list(self._load_topics().values())

    def get(self, topic_id: str) -> Optional[Dict]:
        """Get a topic by ID."""
        return self._load_topics().get(topic_id)

    def get_by_path(self, path: str) -> Optional[Dict]:
        """Get a topic by its path."""
        topic_id = f"topic:{path.lower().replace('/', '_')}"
        return self.get(topic_id)

    def create(self, path: str, data: Dict) -> Dict:
        """Create a new topic."""
        self._load_topics()

        topic_id = f"topic:{path.lower().replace('/', '_')}"
        if topic_id in self._topics:
            raise ValueError(f"Topic already exists: {path}")

        now = datetime.now(LOCAL_TIMEZONE).isoformat()
        topic = {
            "@type": "Topic",
            "@id": topic_id,
            "name": data.get("name") or path.split("/")[-1],
            "path": path,
            "description": data.get("description", ""),
            "examples": data.get("examples", []),
            "created_at": now,
            "updated_at": now
        }

        self._topics[topic_id] = topic
        self._save_topics()
        return topic

    def update(self, topic_id: str, data: Dict) -> Dict:
        """Update a topic."""
        self._load_topics()

        if topic_id not in self._topics:
            raise KeyError(f"Topic not found: {topic_id}")

        topic = self._topics[topic_id]
        for key in ["name", "description", "examples"]:
            if key in data:
                topic[key] = data[key]

        topic["updated_at"] = datetime.now(LOCAL_TIMEZONE).isoformat()
        self._save_topics()
        return topic

    def delete(self, topic_id: str) -> bool:
        """Delete a topic."""
        self._load_topics()

        if topic_id not in self._topics:
            return False

        del self._topics[topic_id]
        self._save_topics()
        return True

    def get_tree(self, root_path: Optional[str] = None) -> List[Dict]:
        """Get topics as a hierarchical tree."""
        topics = self.get_all()

        if root_path:
            topics = [t for t in topics if t.get("path", "").startswith(root_path)]

        # Build tree structure
        by_path = {t.get("path"): t.copy() for t in topics}

        for topic in by_path.values():
            topic["children"] = []

        roots = []
        for path, topic in by_path.items():
            parts = path.rsplit("/", 1)
            if len(parts) == 1:
                roots.append(topic)
            else:
                parent_path = parts[0]
                if parent_path in by_path:
                    by_path[parent_path]["children"].append(topic)
                else:
                    roots.append(topic)

        return roots

    def get_children(self, parent_path: str) -> List[Dict]:
        """Get direct children of a topic."""
        topics = self.get_all()
        children = []

        for topic in topics:
            path = topic.get("path", "")
            if path.startswith(parent_path + "/"):
                # Check if direct child (no additional slashes)
                remainder = path[len(parent_path) + 1:]
                if "/" not in remainder:
                    children.append(topic)

        return children

    def move(self, topic_id: str, new_parent_path: str) -> Dict:
        """Move a topic to a new parent."""
        self._load_topics()

        if topic_id not in self._topics:
            raise KeyError(f"Topic not found: {topic_id}")

        topic = self._topics[topic_id]
        old_path = topic.get("path", "")
        name = old_path.split("/")[-1]
        new_path = f"{new_parent_path}/{name}" if new_parent_path else name

        # Update this topic
        topic["path"] = new_path
        new_id = f"topic:{new_path.lower().replace('/', '_')}"

        if new_id != topic_id:
            del self._topics[topic_id]
            topic["@id"] = new_id
            self._topics[new_id] = topic

        # Update children paths
        for tid, t in list(self._topics.items()):
            if t.get("path", "").startswith(old_path + "/"):
                child_new_path = new_path + t["path"][len(old_path):]
                t["path"] = child_new_path
                child_new_id = f"topic:{child_new_path.lower().replace('/', '_')}"
                if child_new_id != tid:
                    del self._topics[tid]
                    t["@id"] = child_new_id
                    self._topics[child_new_id] = t

        topic["updated_at"] = datetime.now(LOCAL_TIMEZONE).isoformat()
        self._save_topics()
        return topic

    def merge(self, source_id: str, target_id: str) -> Dict:
        """Merge source topic into target (delete source, reassign items)."""
        self._load_topics()

        if source_id not in self._topics:
            raise KeyError(f"Source topic not found: {source_id}")
        if target_id not in self._topics:
            raise KeyError(f"Target topic not found: {target_id}")

        source = self._topics[source_id]
        target = self._topics[target_id]

        # Merge examples
        source_examples = source.get("examples", [])
        target_examples = target.get("examples", [])
        target["examples"] = list(set(target_examples + source_examples))

        # Delete source
        del self._topics[source_id]

        target["updated_at"] = datetime.now(LOCAL_TIMEZONE).isoformat()
        self._save_topics()

        return {
            "merged_into": target,
            "source_deleted": source_id,
            "note": "Tasks with source topic should be updated to use target topic"
        }

    def search(self, query: str) -> List[Dict]:
        """Search topics by name, path, or description."""
        query_lower = query.lower()
        topics = self.get_all()
        results = []

        for topic in topics:
            score = 0
            name = topic.get("name", "").lower()
            path = topic.get("path", "").lower()
            desc = topic.get("description", "").lower()

            if query_lower in name:
                score += 10
            if query_lower in path:
                score += 5
            if query_lower in desc:
                score += 2

            if score > 0:
                results.append((score, topic))

        results.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in results]


def get_store() -> TopicStore:
    """Create and return the topic store."""
    bucket_name = os.environ.get("GCS_BUCKET")
    if not bucket_name:
        raise ValueError("GCS_BUCKET environment variable not set")
    return TopicStore(bucket_name)


def parse_json(request: Request) -> dict:
    """Parse JSON from request body."""
    try:
        return request.get_json(force=True) or {}
    except Exception:
        return {}


def json_response(data: dict, status: int = 200):
    """Create a JSON response tuple."""
    return data, status, {"Content-Type": "application/json"}


@functions_framework.http
def topic_api(request: Request):
    """Main HTTP API entry point for topic management.

    Routes:
        GET    /                   - List all topics
        GET    /tree               - Get hierarchical tree
        GET    /{id}               - Get topic by ID
        GET    /path/{path}        - Get topic by path
        POST   /                   - Create topic
        PUT    /{id}               - Update topic
        DELETE /{id}               - Delete topic
        GET    /{id}/children      - Get children
        POST   /{id}/move          - Move topic
        POST   /merge              - Merge topics
        GET    /search             - Search topics
    """
    try:
        store = get_store()
        path = request.path.strip("/")
        path_parts = path.split("/") if path else []
        method = request.method

        # GET / - List all topics
        if method == "GET" and len(path_parts) == 0:
            topics = store.get_all()
            return json_response({"count": len(topics), "topics": topics})

        # GET /tree - Get hierarchical tree
        if method == "GET" and path_parts == ["tree"]:
            root = request.args.get("root")
            tree = store.get_tree(root)
            return json_response({"tree": tree})

        # GET /search - Search topics
        if method == "GET" and path_parts == ["search"]:
            query = request.args.get("q", "")
            if not query:
                return json_response({"error": "q parameter required"}, 400)
            results = store.search(query)
            return json_response({"count": len(results), "topics": results})

        # POST / - Create topic
        if method == "POST" and len(path_parts) == 0:
            body = parse_json(request)
            path_value = body.get("path")
            if not path_value:
                return json_response({"error": "path is required"}, 400)

            try:
                topic = store.create(path_value, body)
                log_structured("INFO", f"Created topic: {topic['@id']}", event="topic_created")
                return json_response({"topic": topic}, 201)
            except ValueError as e:
                return json_response({"error": str(e)}, 409)

        # POST /merge - Merge topics
        if method == "POST" and path_parts == ["merge"]:
            body = parse_json(request)
            source_id = body.get("source_id")
            target_id = body.get("target_id")
            if not source_id or not target_id:
                return json_response({"error": "source_id and target_id required"}, 400)

            try:
                result = store.merge(source_id, target_id)
                log_structured("INFO", f"Merged {source_id} into {target_id}", event="topic_merged")
                return json_response(result)
            except KeyError as e:
                return json_response({"error": str(e)}, 404)

        # GET /path/{path...} - Get topic by path
        if method == "GET" and len(path_parts) >= 2 and path_parts[0] == "path":
            topic_path = "/".join(path_parts[1:])
            topic = store.get_by_path(topic_path)
            if not topic:
                return json_response({"error": "Topic not found"}, 404)
            return json_response({"topic": topic})

        # Routes with topic ID
        if len(path_parts) >= 1:
            # Handle topic ID (may contain colons)
            topic_id = path_parts[0]
            if not topic_id.startswith("topic:"):
                topic_id = f"topic:{topic_id}"

            # GET /{id} - Get topic
            if method == "GET" and len(path_parts) == 1:
                topic = store.get(topic_id)
                if not topic:
                    return json_response({"error": "Topic not found"}, 404)
                return json_response({"topic": topic})

            # PUT /{id} - Update topic
            if method == "PUT" and len(path_parts) == 1:
                body = parse_json(request)
                try:
                    topic = store.update(topic_id, body)
                    log_structured("INFO", f"Updated topic: {topic_id}", event="topic_updated")
                    return json_response({"topic": topic})
                except KeyError:
                    return json_response({"error": "Topic not found"}, 404)

            # DELETE /{id} - Delete topic
            if method == "DELETE" and len(path_parts) == 1:
                deleted = store.delete(topic_id)
                if not deleted:
                    return json_response({"error": "Topic not found"}, 404)
                log_structured("INFO", f"Deleted topic: {topic_id}", event="topic_deleted")
                return json_response({"success": True, "topic_id": topic_id})

            # GET /{id}/children - Get children
            if method == "GET" and len(path_parts) == 2 and path_parts[1] == "children":
                topic = store.get(topic_id)
                if not topic:
                    return json_response({"error": "Topic not found"}, 404)
                children = store.get_children(topic.get("path", ""))
                return json_response({"count": len(children), "children": children})

            # POST /{id}/move - Move topic
            if method == "POST" and len(path_parts) == 2 and path_parts[1] == "move":
                body = parse_json(request)
                new_parent = body.get("new_parent_path", "")
                try:
                    topic = store.move(topic_id, new_parent)
                    log_structured("INFO", f"Moved topic {topic_id} to {new_parent}", event="topic_moved")
                    return json_response({"topic": topic})
                except KeyError:
                    return json_response({"error": "Topic not found"}, 404)

        return json_response({"error": "Not found", "path": request.path}, 404)

    except Exception as e:
        log_structured("ERROR", f"API error: {e}", error=str(e), path=request.path)
        return json_response({"error": str(e)}, 500)


@functions_framework.http
def health_check(request: Request):
    """Health check endpoint."""
    try:
        store = get_store()
        topics = store.get_all()
        return json_response({
            "status": "healthy",
            "service": "topic-manager",
            "topic_count": len(topics)
        })
    except Exception as e:
        return json_response({
            "status": "unhealthy",
            "service": "topic-manager",
            "error": str(e)
        }, 500)
