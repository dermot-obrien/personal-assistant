"""
Task Consolidator Cloud Function

Listens to task-extracted-events Pub/Sub topic and consolidates all extracted tasks
into a single master file with comprehensive metadata.

Triggered by: Pub/Sub messages from task-extractor function
Output: Consolidated task record updated in GCS as JSON
"""

import base64
import json
import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import functions_framework
from google.cloud import storage
from cloudevents.http import CloudEvent

# Local timezone (configurable via LOCAL_TIMEZONE env var)
LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "Pacific/Auckland"))

# Output file path in GCS
CONSOLIDATED_FILE = "tasks/consolidated_tasks.json"


def log_structured(severity: str, message: str, **kwargs):
    """Output structured JSON log for Cloud Logging."""
    log_entry = {
        "severity": severity,
        "message": message,
        "component": "task-consolidator",
        **kwargs
    }
    print(json.dumps(log_entry))


def get_consolidated_tasks(bucket_name: str) -> dict:
    """Load the consolidated tasks file from GCS.

    Returns:
        Dict with consolidated tasks structure
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(CONSOLIDATED_FILE)

    default_structure = {
        "version": "1.0",
        "description": "Consolidated tasks from all transcripts",
        "last_updated": None,
        "total_tasks": 0,
        "sources": {},  # transcript_id -> source metadata
        "tasks": [],    # All tasks with source references
        "by_topic": {}, # Tasks grouped by primary_topic
        "by_assignee": {}, # Tasks grouped by assignee
        "by_priority": {"high": [], "medium": [], "low": []}  # Tasks grouped by priority
    }

    if blob.exists():
        try:
            content = blob.download_as_text()
            data = json.loads(content)
            log_structured("INFO", f"Loaded existing consolidated file with {data.get('total_tasks', 0)} tasks",
                          event="consolidated_loaded",
                          total_tasks=data.get("total_tasks", 0))
            return data
        except Exception as e:
            log_structured("WARNING", f"Failed to load consolidated file: {e}, starting fresh",
                          event="consolidated_load_error", error=str(e))

    log_structured("INFO", "Starting with empty consolidated file",
                  event="consolidated_new")
    return default_structure


def save_consolidated_tasks(bucket_name: str, data: dict) -> str:
    """Save the consolidated tasks file to GCS.

    Returns:
        The blob path where file was saved
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(CONSOLIDATED_FILE)

    blob.upload_from_string(
        json.dumps(data, indent=2, ensure_ascii=False),
        content_type="application/json"
    )

    # Add metadata
    blob.metadata = {
        "total_tasks": str(data.get("total_tasks", 0)),
        "source_count": str(len(data.get("sources", {}))),
        "last_updated": data.get("last_updated", "")
    }
    blob.patch()

    return CONSOLIDATED_FILE


def get_task_file(bucket_name: str, blob_path: str) -> Optional[dict]:
    """Download and parse task JSON from GCS."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    if not blob.exists():
        log_structured("WARNING", f"Task file not found: {blob_path}",
                      event="task_file_not_found",
                      blob_path=blob_path)
        return None

    try:
        content = blob.download_as_text()
        return json.loads(content)
    except Exception as e:
        log_structured("ERROR", f"Failed to read task file: {e}",
                      event="task_file_error",
                      blob_path=blob_path,
                      error=str(e))
        return None


def rebuild_indexes(data: dict) -> dict:
    """Rebuild the by_topic, by_assignee, and by_priority indexes from tasks list.

    Args:
        data: The consolidated tasks data structure

    Returns:
        Updated data with rebuilt indexes
    """
    data["by_topic"] = {}
    data["by_assignee"] = {}
    data["by_priority"] = {"high": [], "medium": [], "low": []}

    for i, task in enumerate(data.get("tasks", [])):
        task_ref = {
            "index": i,
            "description": task.get("description", ""),
            "source_transcript_id": task.get("source_transcript_id", ""),
            "deadline": task.get("deadline")
        }

        # Index by primary topic
        primary_topic = task.get("primary_topic", "General")
        if primary_topic not in data["by_topic"]:
            data["by_topic"][primary_topic] = []
        data["by_topic"][primary_topic].append(task_ref)

        # Index by assignee
        assignee = task.get("assignee") or "Unassigned"
        if assignee not in data["by_assignee"]:
            data["by_assignee"][assignee] = []
        data["by_assignee"][assignee].append(task_ref)

        # Index by priority
        priority = task.get("priority", "medium").lower()
        if priority not in data["by_priority"]:
            priority = "medium"
        data["by_priority"][priority].append(task_ref)

    return data


def add_tasks_from_source(data: dict, task_file: dict, event: dict) -> dict:
    """Add tasks from a source file to the consolidated data.

    Args:
        data: The consolidated tasks data structure
        task_file: The task file content from task-extractor
        event: The Pub/Sub event data

    Returns:
        Updated consolidated data
    """
    transcript_id = event.get("transcript_id", "unknown")
    now = datetime.now(LOCAL_TIMEZONE)

    # Check if we already have tasks from this source
    if transcript_id in data.get("sources", {}):
        # Remove existing tasks from this source before adding new ones
        existing_source = data["sources"][transcript_id]
        log_structured("INFO", f"Updating existing source: {transcript_id}",
                      event="source_update",
                      transcript_id=transcript_id,
                      previous_task_count=existing_source.get("task_count", 0))

        # Filter out tasks from this source
        data["tasks"] = [
            t for t in data.get("tasks", [])
            if t.get("source_transcript_id") != transcript_id
        ]

    # Add source metadata
    source_info = task_file.get("source", {})
    data["sources"][transcript_id] = {
        "transcript_id": transcript_id,
        "transcript_title": event.get("transcript_title") or source_info.get("transcript_title", "Untitled"),
        "transcript_topic": event.get("transcript_topic") or source_info.get("transcript_topic", "General"),
        "transcript_created_at": event.get("transcript_created_at") or source_info.get("transcript_created_at", ""),
        "tasks_gcs_path": event.get("gcs_path", ""),
        "tasks_gcs_blob": event.get("gcs_blob", ""),
        "task_count": task_file.get("task_count", 0),
        "extracted_at": task_file.get("extracted_at", ""),
        "consolidated_at": now.isoformat(),
        "summary": task_file.get("summary", "")
    }

    # Add each task with source reference
    for task in task_file.get("tasks", []):
        enriched_task = {
            **task,
            "source_transcript_id": transcript_id,
            "source_transcript_title": data["sources"][transcript_id]["transcript_title"],
            "source_transcript_topic": data["sources"][transcript_id]["transcript_topic"],
            "source_transcript_created_at": data["sources"][transcript_id]["transcript_created_at"],
            "consolidated_at": now.isoformat()
        }
        data["tasks"].append(enriched_task)

    # Update totals
    data["total_tasks"] = len(data["tasks"])
    data["last_updated"] = now.isoformat()

    # Rebuild indexes
    data = rebuild_indexes(data)

    return data


@functions_framework.cloud_event
def process_tasks_event(cloud_event: CloudEvent):
    """Process incoming Pub/Sub messages about extracted tasks.

    This function is triggered by Pub/Sub messages from the task-extractor function.
    """
    start_time = datetime.now(LOCAL_TIMEZONE)

    # Decode the Pub/Sub message
    try:
        message_data = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
        event = json.loads(message_data)
    except Exception as e:
        log_structured("ERROR", f"Failed to decode Pub/Sub message: {e}",
                      event="decode_error", error=str(e))
        return

    log_structured("INFO", f"Processing tasks event: {event.get('transcript_title')}",
                  event="event_received",
                  transcript_id=event.get("transcript_id"),
                  transcript_title=event.get("transcript_title"),
                  task_count=event.get("task_count"))

    # Get configuration
    bucket_name = event.get("gcs_bucket") or os.environ.get("GCS_BUCKET")
    tasks_blob = event.get("gcs_blob")

    if not all([bucket_name, tasks_blob]):
        log_structured("ERROR", "Missing required configuration",
                      event="config_error",
                      bucket_name=bucket_name,
                      tasks_blob=tasks_blob)
        return

    try:
        # Load the task file from GCS
        task_file = get_task_file(bucket_name, tasks_blob)
        if not task_file:
            log_structured("WARNING", "Could not load task file, skipping",
                          event="skip_missing_file",
                          tasks_blob=tasks_blob)
            return

        # Skip if no tasks were extracted
        if not task_file.get("tasks"):
            log_structured("INFO", "No tasks in file, skipping consolidation",
                          event="skip_no_tasks",
                          transcript_id=event.get("transcript_id"))
            return

        # Load existing consolidated file
        consolidated = get_consolidated_tasks(bucket_name)

        # Add/update tasks from this source
        consolidated = add_tasks_from_source(consolidated, task_file, event)

        # Save updated consolidated file
        save_consolidated_tasks(bucket_name, consolidated)

        duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)
        log_structured("INFO", f"Consolidation complete: {consolidated['total_tasks']} total tasks from {len(consolidated['sources'])} sources",
                      event="processing_completed",
                      transcript_id=event.get("transcript_id"),
                      new_task_count=event.get("task_count"),
                      total_tasks=consolidated["total_tasks"],
                      source_count=len(consolidated["sources"]),
                      duration_ms=duration_ms)

    except Exception as e:
        duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)
        log_structured("ERROR", f"Failed to consolidate tasks: {e}",
                      event="processing_failed",
                      error=str(e),
                      error_type=type(e).__name__,
                      duration_ms=duration_ms)
        raise


@functions_framework.http
def rebuild_consolidated(request):
    """HTTP endpoint to rebuild the consolidated file from all task files.

    This is useful for:
    - Initial setup to consolidate existing tasks
    - Recovery if the consolidated file becomes corrupted
    - Force refresh of all indexes

    Query parameters:
    - dry_run: If 'true', only lists what would be consolidated without writing
    """
    start_time = datetime.now(LOCAL_TIMEZONE)

    bucket_name = os.environ.get("GCS_BUCKET")
    if not bucket_name:
        return {"error": "GCS_BUCKET environment variable not set"}, 500

    dry_run = request.args.get("dry_run", "").lower() == "true"

    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)

        # List all task files
        task_files = []
        blobs = bucket.list_blobs(prefix="tasks/")

        for blob in blobs:
            # Skip the consolidated file itself and any non-JSON files
            if blob.name == CONSOLIDATED_FILE or not blob.name.endswith(".json"):
                continue
            task_files.append(blob.name)

        log_structured("INFO", f"Found {len(task_files)} task files to consolidate",
                      event="rebuild_started",
                      file_count=len(task_files),
                      dry_run=dry_run)

        if dry_run:
            return {
                "dry_run": True,
                "task_files_found": len(task_files),
                "files": task_files
            }, 200

        # Start fresh
        consolidated = {
            "version": "1.0",
            "description": "Consolidated tasks from all transcripts",
            "last_updated": None,
            "total_tasks": 0,
            "sources": {},
            "tasks": [],
            "by_topic": {},
            "by_assignee": {},
            "by_priority": {"high": [], "medium": [], "low": []}
        }

        # Process each task file
        processed = 0
        errors = []

        for blob_path in task_files:
            try:
                task_file = get_task_file(bucket_name, blob_path)
                if not task_file or not task_file.get("tasks"):
                    continue

                # Build event-like structure from task file
                source = task_file.get("source", {})
                event = {
                    "transcript_id": source.get("transcript_id", blob_path),
                    "transcript_title": source.get("transcript_title", "Untitled"),
                    "transcript_topic": source.get("transcript_topic", "General"),
                    "transcript_created_at": source.get("transcript_created_at", ""),
                    "gcs_bucket": bucket_name,
                    "gcs_blob": blob_path,
                    "gcs_path": f"gs://{bucket_name}/{blob_path}"
                }

                consolidated = add_tasks_from_source(consolidated, task_file, event)
                processed += 1

            except Exception as e:
                errors.append({"file": blob_path, "error": str(e)})
                log_structured("WARNING", f"Error processing {blob_path}: {e}",
                              event="rebuild_file_error",
                              blob_path=blob_path,
                              error=str(e))

        # Save the rebuilt consolidated file
        save_consolidated_tasks(bucket_name, consolidated)

        duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)

        result = {
            "success": True,
            "files_processed": processed,
            "total_tasks": consolidated["total_tasks"],
            "source_count": len(consolidated["sources"]),
            "topics": list(consolidated["by_topic"].keys()),
            "assignees": list(consolidated["by_assignee"].keys()),
            "duration_ms": duration_ms
        }

        if errors:
            result["errors"] = errors

        log_structured("INFO", f"Rebuild complete: {processed} files, {consolidated['total_tasks']} tasks",
                      event="rebuild_completed",
                      files_processed=processed,
                      total_tasks=consolidated["total_tasks"],
                      duration_ms=duration_ms)

        return result, 200

    except Exception as e:
        log_structured("ERROR", f"Rebuild failed: {e}",
                      event="rebuild_failed",
                      error=str(e))
        return {"error": str(e)}, 500


@functions_framework.http
def get_tasks(request):
    """HTTP endpoint to retrieve consolidated tasks with optional filtering.

    Query parameters:
    - topic: Filter by primary_topic (supports prefix matching, e.g., 'Work' matches 'Work/Projects')
    - assignee: Filter by assignee name
    - priority: Filter by priority (high, medium, low)
    - limit: Maximum number of tasks to return (default: 100)
    - format: Output format ('full', 'summary', 'by_topic', 'by_assignee', 'by_priority')
    """
    bucket_name = os.environ.get("GCS_BUCKET")
    if not bucket_name:
        return {"error": "GCS_BUCKET environment variable not set"}, 500

    try:
        consolidated = get_consolidated_tasks(bucket_name)

        # Get query parameters
        topic_filter = request.args.get("topic")
        assignee_filter = request.args.get("assignee")
        priority_filter = request.args.get("priority")
        limit = int(request.args.get("limit", 100))
        output_format = request.args.get("format", "full")

        # Start with all tasks
        tasks = consolidated.get("tasks", [])

        # Apply filters
        if topic_filter:
            tasks = [t for t in tasks if t.get("primary_topic", "").startswith(topic_filter)]

        if assignee_filter:
            if assignee_filter.lower() == "unassigned":
                tasks = [t for t in tasks if not t.get("assignee")]
            else:
                tasks = [t for t in tasks if (t.get("assignee") or "").lower() == assignee_filter.lower()]

        if priority_filter:
            tasks = [t for t in tasks if t.get("priority", "").lower() == priority_filter.lower()]

        # Apply limit
        tasks = tasks[:limit]

        # Format output
        if output_format == "summary":
            return {
                "total_tasks": consolidated.get("total_tasks", 0),
                "filtered_count": len(tasks),
                "source_count": len(consolidated.get("sources", {})),
                "last_updated": consolidated.get("last_updated"),
                "topics": list(consolidated.get("by_topic", {}).keys()),
                "assignees": list(consolidated.get("by_assignee", {}).keys())
            }, 200

        elif output_format == "by_topic":
            return {
                "last_updated": consolidated.get("last_updated"),
                "by_topic": consolidated.get("by_topic", {})
            }, 200

        elif output_format == "by_assignee":
            return {
                "last_updated": consolidated.get("last_updated"),
                "by_assignee": consolidated.get("by_assignee", {})
            }, 200

        elif output_format == "by_priority":
            return {
                "last_updated": consolidated.get("last_updated"),
                "by_priority": consolidated.get("by_priority", {})
            }, 200

        else:  # full
            return {
                "total_tasks": consolidated.get("total_tasks", 0),
                "filtered_count": len(tasks),
                "source_count": len(consolidated.get("sources", {})),
                "last_updated": consolidated.get("last_updated"),
                "tasks": tasks,
                "sources": consolidated.get("sources", {})
            }, 200

    except Exception as e:
        log_structured("ERROR", f"Failed to get tasks: {e}",
                      event="get_tasks_error",
                      error=str(e))
        return {"error": str(e)}, 500


@functions_framework.http
def health_check(request):
    """Simple health check endpoint."""
    return {"status": "healthy"}, 200
