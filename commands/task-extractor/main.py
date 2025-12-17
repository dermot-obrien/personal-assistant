"""
Task Extractor Cloud Function

Listens to otter-transcript-events Pub/Sub topic and extracts tasks from transcripts.
Uses Google's Gemini API to identify tasks and classify them by topic.

Triggered by: Pub/Sub messages from otter-sync function
Output: Task records saved to GCS as JSON
"""

import base64
import json
import os
import re
from datetime import datetime
from typing import Optional, List
from zoneinfo import ZoneInfo

import functions_framework
from google.cloud import storage, pubsub_v1
from cloudevents.http import CloudEvent

# Vertex AI / Gemini imports
import vertexai
from vertexai.generative_models import GenerativeModel, Part, GenerationConfig

# Local timezone (configurable via LOCAL_TIMEZONE env var)
LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "Pacific/Auckland"))


def log_structured(severity: str, message: str, **kwargs):
    """Output structured JSON log for Cloud Logging."""
    log_entry = {
        "severity": severity,
        "message": message,
        "component": "task-extractor",
        **kwargs
    }
    print(json.dumps(log_entry))


# Cache for topic taxonomy (loaded once per cold start)
_topic_taxonomy_cache: Optional[dict] = None


def get_topic_taxonomy(bucket_name: str) -> dict:
    """Load topic taxonomy from GCS bucket.

    The taxonomy file (topic_taxonomy.json) defines the hierarchical topic structure
    for task classification. It includes topic paths, descriptions, and examples.

    Args:
        bucket_name: GCS bucket containing the taxonomy file

    Returns:
        Dict with taxonomy structure, or default taxonomy if file not found
    """
    global _topic_taxonomy_cache

    # Return cached taxonomy if available
    if _topic_taxonomy_cache is not None:
        return _topic_taxonomy_cache

    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob("topic_taxonomy.json")

    default_taxonomy = {
        "version": "1.0",
        "description": "Default topic taxonomy for task classification",
        "topics": [
            {"path": "Work/Projects", "description": "Project-specific tasks", "examples": ["feature development", "bug fixes"]},
            {"path": "Work/Meetings", "description": "Meeting action items"},
            {"path": "Work/Admin", "description": "Administrative tasks"},
            {"path": "Work/Finance", "description": "Work-related financial tasks"},
            {"path": "Personal/Health", "description": "Health and wellness tasks"},
            {"path": "Personal/Finance", "description": "Personal financial tasks"},
            {"path": "Personal/Learning", "description": "Learning and development"},
            {"path": "Personal/Journal", "description": "Personal reflections and notes"},
            {"path": "General", "description": "Uncategorized tasks"}
        ]
    }

    if blob.exists():
        try:
            content = blob.download_as_text()
            taxonomy = json.loads(content)
            log_structured("INFO", f"Loaded topic taxonomy with {len(taxonomy.get('topics', []))} topics",
                          event="taxonomy_loaded",
                          topic_count=len(taxonomy.get("topics", [])),
                          version=taxonomy.get("version", "unknown"))
            _topic_taxonomy_cache = taxonomy
            return taxonomy
        except Exception as e:
            log_structured("WARNING", f"Failed to load topic taxonomy: {e}, using defaults",
                          event="taxonomy_load_error", error=str(e))

    log_structured("INFO", "Using default topic taxonomy",
                  event="taxonomy_default")
    _topic_taxonomy_cache = default_taxonomy
    return default_taxonomy


def format_taxonomy_for_prompt(taxonomy: dict) -> str:
    """Format topic taxonomy as a string for the Gemini prompt.

    Args:
        taxonomy: The topic taxonomy dict

    Returns:
        Formatted string listing all topics with descriptions
    """
    lines = []
    for topic in taxonomy.get("topics", []):
        path = topic.get("path", "Unknown")
        description = topic.get("description", "")
        examples = topic.get("examples", [])

        line = f"- {path}"
        if description:
            line += f": {description}"
        if examples:
            line += f" (e.g., {', '.join(examples)})"
        lines.append(line)

    return "\n".join(lines)


def get_taxonomy_paths(taxonomy: dict) -> List[str]:
    """Extract list of valid taxonomy paths from taxonomy dict.

    Args:
        taxonomy: The topic taxonomy dict

    Returns:
        List of valid taxonomy path strings
    """
    paths = [topic.get("path") for topic in taxonomy.get("topics", []) if topic.get("path")]
    # Ensure "General" is always available as fallback
    if "General" not in paths:
        paths.append("General")
    return paths


def build_response_schema(taxonomy_paths: List[str]) -> dict:
    """Build JSON schema for constrained Gemini output.

    This schema enforces that:
    - primary_topic must be one of the taxonomy paths
    - secondary_topics must all be from taxonomy paths
    - priority must be high/medium/low

    Args:
        taxonomy_paths: List of valid taxonomy path strings

    Returns:
        JSON schema dict for Gemini response_schema parameter
    """
    return {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "description": "List of extracted tasks and action items",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "Clear, actionable task description"
                        },
                        "assignee": {
                            "type": "string",
                            "description": "Person responsible for the task, or null if not specified",
                            "nullable": True
                        },
                        "deadline": {
                            "type": "string",
                            "description": "Deadline or timeframe mentioned, or null if not specified",
                            "nullable": True
                        },
                        "primary_topic": {
                            "type": "string",
                            "description": "Primary category from the taxonomy",
                            "enum": taxonomy_paths
                        },
                        "secondary_topics": {
                            "type": "array",
                            "description": "Related categories from the taxonomy",
                            "items": {
                                "type": "string",
                                "enum": taxonomy_paths
                            }
                        },
                        "priority": {
                            "type": "string",
                            "description": "Task priority based on urgency and importance",
                            "enum": ["high", "medium", "low"]
                        },
                        "context": {
                            "type": "string",
                            "description": "Brief context from the transcript explaining the task",
                            "nullable": True
                        }
                    },
                    "required": ["description", "primary_topic", "priority"]
                }
            },
            "summary": {
                "type": "string",
                "description": "Brief summary of all action items identified"
            }
        },
        "required": ["tasks", "summary"]
    }


def validate_and_fix_tasks(tasks_result: dict, taxonomy_paths: List[str]) -> dict:
    """Validate and fix task classifications against taxonomy.

    Belt-and-suspenders validation to ensure all topics are valid,
    even though the schema should enforce this.

    Args:
        tasks_result: The extraction result from Gemini
        taxonomy_paths: List of valid taxonomy paths

    Returns:
        Validated and fixed tasks result
    """
    taxonomy_set = set(taxonomy_paths)

    for task in tasks_result.get("tasks", []):
        # Validate primary_topic
        if task.get("primary_topic") not in taxonomy_set:
            log_structured("WARNING", f"Invalid primary_topic '{task.get('primary_topic')}', defaulting to 'General'",
                          event="invalid_topic_fixed",
                          original_topic=task.get("primary_topic"))
            task["primary_topic"] = "General"

        # Validate secondary_topics
        if "secondary_topics" in task:
            valid_secondary = [t for t in task["secondary_topics"] if t in taxonomy_set]
            if len(valid_secondary) != len(task["secondary_topics"]):
                invalid = set(task["secondary_topics"]) - set(valid_secondary)
                log_structured("WARNING", f"Removed invalid secondary_topics: {invalid}",
                              event="invalid_secondary_topics_fixed",
                              removed_topics=list(invalid))
            task["secondary_topics"] = valid_secondary

        # Validate priority
        if task.get("priority") not in ("high", "medium", "low"):
            task["priority"] = "medium"

    return tasks_result


def get_transcript_content(bucket_name: str, blob_path: str) -> dict:
    """Download and parse transcript JSON from GCS."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    content = blob.download_as_text()
    return json.loads(content)


def get_processed_tasks_state(bucket_name: str) -> dict:
    """Load the processed tasks state from GCS.

    The state file tracks which transcripts have had tasks extracted,
    avoiding duplicate processing on republished events.

    Returns:
        Dict mapping transcript_id -> tasks_blob_path
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(".task_extractor_state.json")

    if blob.exists():
        try:
            content = blob.download_as_text()
            return json.loads(content)
        except Exception as e:
            log_structured("WARNING", f"Failed to load task extractor state: {e}",
                          event="state_load_error", error=str(e))

    return {}


def save_processed_tasks_state(bucket_name: str, state: dict) -> None:
    """Save the processed tasks state to GCS."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(".task_extractor_state.json")

    blob.upload_from_string(
        json.dumps(state, indent=2, ensure_ascii=False),
        content_type="application/json"
    )


def is_already_processed(bucket_name: str, transcript_id: str, state: dict) -> tuple[bool, Optional[str]]:
    """Check if tasks have already been extracted for this transcript.

    Uses the task extractor state file for fast lookup.

    Args:
        bucket_name: GCS bucket name
        transcript_id: The Otter transcript ID
        state: The task extractor state dict

    Returns:
        Tuple of (is_processed, existing_path)
    """
    if transcript_id in state:
        existing_path = state[transcript_id]
        # Verify the tasks file still exists
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(existing_path)
        if blob.exists():
            return True, existing_path
        # File was deleted, remove from state
        log_structured("WARNING", f"Tasks file missing, will re-process: {existing_path}",
                      event="tasks_file_missing",
                      transcript_id=transcript_id,
                      expected_path=existing_path)

    return False, None


def extract_tasks_with_gemini(
    transcript: dict,
    project_id: str,
    taxonomy: dict,
    location: str = "us-central1"
) -> dict:
    """Use Gemini to extract tasks and classify them by topic.

    Uses constrained output via response_schema to guarantee that:
    - All primary_topic values are valid taxonomy paths
    - All secondary_topics values are valid taxonomy paths
    - Priority is always high/medium/low

    Args:
        transcript: The full transcript JSON
        project_id: GCP project ID for Vertex AI
        taxonomy: Topic taxonomy dict for classification
        location: Vertex AI location

    Returns:
        Dict with extracted tasks and metadata
    """
    # Initialize Vertex AI
    vertexai.init(project=project_id, location=location)

    # Use Gemini 2.0 Flash for fast, cost-effective extraction with schema support
    # Note: response_schema requires gemini-1.5-pro, gemini-1.5-flash, or gemini-2.0-flash
    model = GenerativeModel("gemini-2.0-flash")

    # Use full_text field if available, otherwise build from segments
    transcript_text = transcript.get("full_text", "")

    if not transcript_text:
        # Fallback: build from segments
        segments = transcript.get("segments", [])
        if isinstance(segments, list):
            for segment in segments:
                speaker = segment.get("speaker", "Unknown")
                text = segment.get("text", "")
                transcript_text += f"{speaker}: {text}\n"
        elif isinstance(segments, str):
            transcript_text = segments

    # If still no transcript text, use summary
    if not transcript_text.strip():
        transcript_text = transcript.get("summary", "") or transcript.get("short_abstract_summary", "") or ""

    if not transcript_text.strip():
        return {"tasks": [], "summary": "No action items identified", "error": "No transcript content available"}

    # Get taxonomy paths for schema constraint
    taxonomy_paths = get_taxonomy_paths(taxonomy)

    # Build the response schema with taxonomy constraints
    response_schema = build_response_schema(taxonomy_paths)

    # Get the primary topic from the transcript for context
    primary_topic = transcript.get("topic", "General")

    # Format the taxonomy for the prompt (helps model understand categories)
    taxonomy_text = format_taxonomy_for_prompt(taxonomy)

    # Simplified prompt - schema handles output structure
    prompt = f"""Extract all tasks, action items, and commitments from this transcript.

For each task:
- Write a clear, actionable description
- Identify the assignee if mentioned
- Note any deadline or timeframe
- Classify into the most appropriate topic category
- Assign priority (high/medium/low) based on urgency cues

The transcript's overall topic is: {primary_topic}

## Topic Categories (choose from these)
{taxonomy_text}

## Transcript
{transcript_text[:15000]}"""

    # Configure generation with schema constraint
    generation_config = GenerationConfig(
        temperature=0.1,  # Lower temperature for more consistent classification
        max_output_tokens=2048,
        response_mime_type="application/json",
        response_schema=response_schema  # Enforce taxonomy compliance
    )

    try:
        log_structured("DEBUG", "Calling Gemini with constrained output schema",
                      event="gemini_call_started",
                      taxonomy_count=len(taxonomy_paths))

        response = model.generate_content(
            prompt,
            generation_config=generation_config
        )

        # Parse the JSON response (should always be valid due to schema)
        result_text = response.text.strip()

        # Handle potential markdown code blocks (shouldn't happen with response_schema but just in case)
        if result_text.startswith("```"):
            result_text = re.sub(r'^```(?:json)?\n?', '', result_text)
            result_text = re.sub(r'\n?```$', '', result_text)

        result = json.loads(result_text)

        # Validate and fix any edge cases (belt-and-suspenders)
        result = validate_and_fix_tasks(result, taxonomy_paths)

        log_structured("DEBUG", "Gemini extraction successful",
                      event="gemini_call_completed",
                      task_count=len(result.get("tasks", [])))

        return result

    except json.JSONDecodeError as e:
        log_structured("WARNING", f"Failed to parse Gemini response as JSON: {e}",
                      event="gemini_parse_error", error=str(e))
        return {"tasks": [], "summary": "Extraction failed", "error": f"JSON parse error: {str(e)}"}

    except Exception as e:
        log_structured("ERROR", f"Gemini API error: {e}",
                      event="gemini_api_error", error=str(e))
        return {"tasks": [], "summary": "Extraction failed", "error": str(e)}


def save_tasks(
    bucket_name: str,
    transcript_id: str,
    transcript_title: str,
    transcript_topic: str,
    tasks_result: dict,
    transcript_created_at: str
) -> str:
    """Save extracted tasks to GCS.

    Returns the blob path where tasks were saved.
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    # Create filename based on transcript
    now = datetime.now(LOCAL_TIMEZONE)
    date_str = now.strftime("%Y-%m-%d")

    # Sanitize title for filename
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in transcript_title)
    safe_title = safe_title[:30].strip()

    blob_path = f"tasks/{date_str}_{safe_title}_{transcript_id}.json"

    # Build the task record
    task_record = {
        "source": {
            "transcript_id": transcript_id,
            "transcript_title": transcript_title,
            "transcript_topic": transcript_topic,
            "transcript_created_at": transcript_created_at
        },
        "extracted_at": now.isoformat(),
        "task_count": len(tasks_result.get("tasks", [])),
        "tasks": tasks_result.get("tasks", []),
        "summary": tasks_result.get("summary", ""),
        "error": tasks_result.get("error")
    }

    blob = bucket.blob(blob_path)
    blob.upload_from_string(
        json.dumps(task_record, indent=2, ensure_ascii=False),
        content_type="application/json"
    )

    # Add metadata
    blob.metadata = {
        "transcript_id": transcript_id,
        "transcript_title": transcript_title,
        "task_count": str(task_record["task_count"]),
        "extracted_at": now.isoformat()
    }
    blob.patch()

    return blob_path


def publish_tasks_event(
    project_id: str,
    topic_id: str,
    transcript_id: str,
    transcript_title: str,
    transcript_topic: str,
    bucket_name: str,
    tasks_blob_path: str,
    task_count: int,
    transcript_created_at: str
) -> None:
    """Publish a Pub/Sub event for extracted tasks.

    Args:
        project_id: GCP project ID
        topic_id: Pub/Sub topic ID to publish to
        transcript_id: Original Otter transcript ID
        transcript_title: Title of the transcript
        transcript_topic: Topic classification of the transcript
        bucket_name: GCS bucket where tasks are stored
        tasks_blob_path: Path to the tasks JSON in GCS
        task_count: Number of tasks extracted
        transcript_created_at: When the original transcript was created
    """
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project_id, topic_id)

    now = datetime.now(LOCAL_TIMEZONE)

    event_data = {
        "event_type": "tasks.extracted",
        "transcript_id": transcript_id,
        "transcript_title": transcript_title,
        "transcript_topic": transcript_topic,
        "task_count": task_count,
        "gcs_path": f"gs://{bucket_name}/{tasks_blob_path}",
        "gcs_bucket": bucket_name,
        "gcs_blob": tasks_blob_path,
        "transcript_created_at": transcript_created_at,
        "extracted_at": now.isoformat()
    }

    message_bytes = json.dumps(event_data).encode("utf-8")
    future = publisher.publish(topic_path, message_bytes)
    future.result()  # Wait for publish to complete

    log_structured("INFO", f"Published tasks.extracted event for transcript: {transcript_id}",
                  event="event_published",
                  transcript_id=transcript_id,
                  task_count=task_count)


@functions_framework.cloud_event
def process_transcript_event(cloud_event: CloudEvent):
    """Process incoming Pub/Sub messages about new transcripts.

    This function is triggered by Pub/Sub messages from the otter-sync function.
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

    log_structured("INFO", f"Processing transcript event: {event.get('title')}",
                  event="event_received",
                  otter_id=event.get("otter_id"),
                  title=event.get("title"),
                  topic=event.get("topic"))

    # Get configuration
    project_id = os.environ.get("GCP_PROJECT")
    bucket_name = event.get("gcs_bucket")
    blob_path = event.get("gcs_blob")

    if not all([project_id, bucket_name, blob_path]):
        log_structured("ERROR", "Missing required configuration",
                      event="config_error",
                      project_id=project_id,
                      bucket_name=bucket_name,
                      blob_path=blob_path)
        return

    try:
        transcript_id = event.get("otter_id", "unknown")

        # Load task extractor state
        tasks_state = get_processed_tasks_state(bucket_name)

        # Check if already processed using state file
        already_processed, existing_path = is_already_processed(bucket_name, transcript_id, tasks_state)
        if already_processed:
            log_structured("INFO", f"Tasks already extracted at {existing_path}, skipping",
                          event="already_processed",
                          transcript_id=transcript_id,
                          existing_path=existing_path)
            return

        # Load topic taxonomy from GCS
        taxonomy = get_topic_taxonomy(bucket_name)

        # Download the transcript
        log_structured("INFO", f"Downloading transcript from gs://{bucket_name}/{blob_path}",
                      event="download_started")
        transcript = get_transcript_content(bucket_name, blob_path)

        # Extract tasks using Gemini
        log_structured("INFO", "Extracting tasks with Gemini",
                      event="extraction_started")
        tasks_result = extract_tasks_with_gemini(transcript, project_id, taxonomy)

        task_count = len(tasks_result.get("tasks", []))
        log_structured("INFO", f"Extracted {task_count} tasks",
                      event="extraction_completed",
                      task_count=task_count)

        # Save the tasks
        transcript_title = event.get("title", "Untitled")
        transcript_topic = event.get("topic", "General")
        transcript_created_at = event.get("created_at", "")

        tasks_path = save_tasks(
            bucket_name=bucket_name,
            transcript_id=transcript_id,
            transcript_title=transcript_title,
            transcript_topic=transcript_topic,
            tasks_result=tasks_result,
            transcript_created_at=transcript_created_at
        )

        # Publish tasks.extracted event if topic is configured
        pubsub_topic = os.environ.get("PUBSUB_TOPIC")
        if pubsub_topic:
            try:
                publish_tasks_event(
                    project_id=project_id,
                    topic_id=pubsub_topic,
                    transcript_id=transcript_id,
                    transcript_title=transcript_title,
                    transcript_topic=transcript_topic,
                    bucket_name=bucket_name,
                    tasks_blob_path=tasks_path,
                    task_count=task_count,
                    transcript_created_at=transcript_created_at
                )
            except Exception as e:
                log_structured("WARNING", f"Failed to publish tasks event: {e}",
                              event="publish_error", error=str(e))

        # Update task extractor state
        tasks_state[transcript_id] = tasks_path
        save_processed_tasks_state(bucket_name, tasks_state)
        log_structured("INFO", "Updated task extractor state",
                      event="state_updated",
                      transcript_id=transcript_id)

        duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)
        log_structured("INFO", f"Task extraction complete: {task_count} tasks saved",
                      event="processing_completed",
                      transcript_id=event.get("otter_id"),
                      task_count=task_count,
                      tasks_path=tasks_path,
                      duration_ms=duration_ms)

    except Exception as e:
        duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)
        log_structured("ERROR", f"Failed to process transcript: {e}",
                      event="processing_failed",
                      error=str(e),
                      error_type=type(e).__name__,
                      duration_ms=duration_ms)
        raise


@functions_framework.http
def health_check(request):
    """Simple health check endpoint."""
    return {"status": "healthy"}, 200
