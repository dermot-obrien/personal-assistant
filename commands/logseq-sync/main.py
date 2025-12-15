"""
Logseq Sync Cloud Function

Listens to task extraction events and updates Logseq journal files in GitHub.
Creates daily journal entries with transcripts and extracted tasks.

Triggered by: Pub/Sub messages from task-extractor function
Output: Updated Logseq journal markdown files in GitHub repository
"""

import base64
import json
import os
import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import functions_framework
import requests
from google.cloud import storage
from cloudevents.http import CloudEvent

# Local timezone (configurable via LOCAL_TIMEZONE env var)
LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "Pacific/Auckland"))


def log_structured(severity: str, message: str, **kwargs):
    """Output structured JSON log for Cloud Logging."""
    log_entry = {
        "severity": severity,
        "message": message,
        "component": "logseq-sync",
        **kwargs
    }
    print(json.dumps(log_entry))


def get_processed_state(bucket_name: str) -> dict:
    """Load the processed state from GCS.

    The state file tracks which transcripts have been synced to Logseq,
    avoiding duplicate entries on republished events.

    Returns:
        Dict mapping transcript_id -> journal_date
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(".logseq_sync_state.json")

    if blob.exists():
        try:
            content = blob.download_as_text()
            return json.loads(content)
        except Exception as e:
            log_structured("WARNING", f"Failed to load logseq sync state: {e}",
                          event="state_load_error", error=str(e))

    return {}


def save_processed_state(bucket_name: str, state: dict) -> None:
    """Save the processed state to GCS."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(".logseq_sync_state.json")

    blob.upload_from_string(
        json.dumps(state, indent=2, ensure_ascii=False),
        content_type="application/json"
    )


def is_already_synced(transcript_id: str, state: dict) -> tuple[bool, Optional[str]]:
    """Check if transcript has already been synced to Logseq.

    Args:
        transcript_id: The Otter transcript ID
        state: The logseq sync state dict

    Returns:
        Tuple of (is_synced, journal_date)
    """
    if transcript_id in state:
        return True, state[transcript_id]
    return False, None


def get_transcript_content(bucket_name: str, blob_path: str) -> dict:
    """Download and parse transcript JSON from GCS."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    content = blob.download_as_text()
    return json.loads(content)


def get_tasks_content(bucket_name: str, transcript_id: str) -> Optional[dict]:
    """Find and download tasks JSON for a transcript from GCS."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    # List tasks files and find one matching the transcript ID
    blobs = bucket.list_blobs(prefix="tasks/")
    for blob in blobs:
        if transcript_id in blob.name and blob.name.endswith(".json"):
            try:
                content = blob.download_as_text()
                return json.loads(content)
            except Exception as e:
                log_structured("WARNING", f"Failed to load tasks file: {e}",
                              event="tasks_load_error", blob=blob.name, error=str(e))

    return None


def get_github_file(
    repo: str,
    path: str,
    token: str,
    branch: str = "main"
) -> tuple[Optional[str], Optional[str]]:
    """Get file content and SHA from GitHub.

    Returns:
        Tuple of (content, sha) or (None, None) if file doesn't exist
    """
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    params = {"ref": branch}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code == 404:
            return None, None
        response.raise_for_status()

        data = response.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]

    except requests.exceptions.RequestException as e:
        log_structured("WARNING", f"Failed to get GitHub file: {e}",
                      event="github_get_error", path=path, error=str(e))
        return None, None


def update_github_file(
    repo: str,
    path: str,
    content: str,
    token: str,
    sha: Optional[str] = None,
    branch: str = "main",
    message: str = "Update journal entry"
) -> bool:
    """Create or update a file in GitHub.

    Args:
        repo: Repository in format "owner/repo"
        path: File path in repository
        content: New file content
        token: GitHub personal access token
        sha: SHA of existing file (required for updates)
        branch: Branch to update
        message: Commit message

    Returns:
        True if successful
    """
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    data = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": branch
    }

    if sha:
        data["sha"] = sha

    try:
        response = requests.put(url, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        return True

    except requests.exceptions.RequestException as e:
        log_structured("ERROR", f"Failed to update GitHub file: {e}",
                      event="github_update_error", path=path, error=str(e))
        return False


def format_transcript_block(transcript: dict, topic: str) -> str:
    """Format transcript as a Logseq block.

    Args:
        transcript: Transcript JSON data
        topic: Topic path for the transcript

    Returns:
        Markdown formatted block
    """
    title = transcript.get("title", "Untitled")
    created_at = transcript.get("created_at", "")
    summary = transcript.get("summary", "") or transcript.get("short_abstract_summary", "")

    # Format time if available
    time_str = ""
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at)
            time_str = dt.strftime("%H:%M")
        except ValueError:
            pass

    lines = []
    lines.append(f"- ## {time_str} {title}" if time_str else f"- ## {title}")
    lines.append(f"  collapsed:: true")
    lines.append(f"  topic:: [[{topic}]]")

    if summary:
        lines.append(f"  - **Summary**: {summary}")

    return "\n".join(lines)


def format_tasks_block(tasks_data: dict) -> str:
    """Format extracted tasks as Logseq blocks.

    Args:
        tasks_data: Tasks JSON data from task-extractor

    Returns:
        Markdown formatted blocks
    """
    tasks = tasks_data.get("tasks", [])
    if not tasks:
        return ""

    lines = []
    lines.append("  - ### Tasks")

    for task in tasks:
        description = task.get("description", "")
        assignee = task.get("assignee")
        deadline = task.get("deadline")
        priority = task.get("priority", "medium")
        topic = task.get("primary_topic", "General")

        # Format as TODO with properties
        todo_line = f"    - TODO {description}"
        lines.append(todo_line)

        # Add properties
        lines.append(f"      priority:: {priority}")
        lines.append(f"      topic:: [[{topic}]]")

        if assignee:
            lines.append(f"      assignee:: {assignee}")
        if deadline:
            lines.append(f"      deadline:: {deadline}")

    return "\n".join(lines)


def get_journal_date(transcript: dict) -> str:
    """Get the journal date for a transcript.

    Uses the transcript's created_at date, or current date as fallback.

    Returns:
        Date string in Logseq format (YYYY_MM_DD)
    """
    created_at = transcript.get("created_at", "")
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at)
            # Convert to local timezone
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=LOCAL_TIMEZONE)
            else:
                dt = dt.astimezone(LOCAL_TIMEZONE)
            return dt.strftime("%Y_%m_%d")
        except ValueError:
            pass

    return datetime.now(LOCAL_TIMEZONE).strftime("%Y_%m_%d")


def build_journal_entry(
    existing_content: Optional[str],
    transcript: dict,
    tasks_data: Optional[dict],
    topic: str
) -> str:
    """Build or update a journal entry with new transcript and tasks.

    Args:
        existing_content: Existing journal file content (or None)
        transcript: Transcript JSON data
        tasks_data: Tasks JSON data (or None)
        topic: Topic path

    Returns:
        Updated journal content
    """
    transcript_id = transcript.get("otter_id", "unknown")

    # Format new blocks
    transcript_block = format_transcript_block(transcript, topic)
    tasks_block = format_tasks_block(tasks_data) if tasks_data else ""

    # Combine blocks
    new_entry = transcript_block
    if tasks_block:
        new_entry += "\n" + tasks_block

    # Add a marker to identify this entry
    entry_marker = f"  otter-id:: {transcript_id}"
    new_entry_with_marker = new_entry.replace("\n  collapsed::", f"\n  {entry_marker.strip()}\n  collapsed::")

    if existing_content:
        # Check if this transcript already exists in the journal
        if f"otter-id:: {transcript_id}" in existing_content:
            log_structured("INFO", "Transcript already in journal, skipping",
                          event="already_in_journal", transcript_id=transcript_id)
            return existing_content

        # Append to existing content
        return existing_content.rstrip() + "\n" + new_entry_with_marker
    else:
        # Create new journal with date header
        return new_entry_with_marker


@functions_framework.cloud_event
def process_task_event(cloud_event: CloudEvent):
    """Process incoming Pub/Sub messages about task extraction.

    This function is triggered when task-extractor completes processing.
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

    log_structured("INFO", f"Processing logseq sync for: {event.get('title')}",
                  event="event_received",
                  otter_id=event.get("otter_id"),
                  title=event.get("title"),
                  topic=event.get("topic"))

    # Get configuration
    bucket_name = event.get("gcs_bucket")
    transcript_blob_path = event.get("gcs_blob")
    github_repo = os.environ.get("GITHUB_REPO")
    github_token = os.environ.get("GITHUB_TOKEN")
    github_branch = os.environ.get("GITHUB_BRANCH", "main")
    journal_path_prefix = os.environ.get("LOGSEQ_JOURNAL_PATH", "journals")

    if not all([bucket_name, transcript_blob_path, github_repo, github_token]):
        log_structured("ERROR", "Missing required configuration",
                      event="config_error",
                      bucket_name=bucket_name,
                      transcript_blob_path=transcript_blob_path,
                      github_repo=github_repo,
                      has_token=bool(github_token))
        return

    try:
        transcript_id = event.get("otter_id", "unknown")
        topic = event.get("topic", "General")

        # Load sync state
        sync_state = get_processed_state(bucket_name)

        # Check if already synced
        already_synced, existing_date = is_already_synced(transcript_id, sync_state)
        if already_synced:
            log_structured("INFO", f"Already synced to journal {existing_date}, skipping",
                          event="already_synced",
                          transcript_id=transcript_id,
                          journal_date=existing_date)
            return

        # Download transcript
        log_structured("INFO", f"Downloading transcript from gs://{bucket_name}/{transcript_blob_path}",
                      event="transcript_download_started")
        transcript = get_transcript_content(bucket_name, transcript_blob_path)

        # Try to find associated tasks
        tasks_data = get_tasks_content(bucket_name, transcript_id)
        if tasks_data:
            log_structured("INFO", f"Found {len(tasks_data.get('tasks', []))} tasks",
                          event="tasks_found",
                          task_count=len(tasks_data.get("tasks", [])))

        # Determine journal date and path
        journal_date = get_journal_date(transcript)
        journal_file_path = f"{journal_path_prefix}/{journal_date}.md"

        log_structured("INFO", f"Updating journal: {journal_file_path}",
                      event="journal_update_started",
                      journal_path=journal_file_path)

        # Get existing journal content from GitHub
        existing_content, sha = get_github_file(
            github_repo,
            journal_file_path,
            github_token,
            github_branch
        )

        # Build updated journal content
        updated_content = build_journal_entry(
            existing_content,
            transcript,
            tasks_data,
            topic
        )

        # Skip if content unchanged
        if existing_content == updated_content:
            log_structured("INFO", "No changes to journal content",
                          event="no_changes")
            return

        # Update GitHub
        commit_message = f"Add transcript: {event.get('title', 'Untitled')}"
        success = update_github_file(
            github_repo,
            journal_file_path,
            updated_content,
            github_token,
            sha,
            github_branch,
            commit_message
        )

        if success:
            # Update state
            sync_state[transcript_id] = journal_date
            save_processed_state(bucket_name, sync_state)

            duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)
            log_structured("INFO", "Logseq sync complete",
                          event="processing_completed",
                          transcript_id=transcript_id,
                          journal_path=journal_file_path,
                          duration_ms=duration_ms)
        else:
            log_structured("ERROR", "Failed to update GitHub",
                          event="github_update_failed",
                          transcript_id=transcript_id)

    except Exception as e:
        duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)
        log_structured("ERROR", f"Failed to sync to Logseq: {e}",
                      event="processing_failed",
                      error=str(e),
                      error_type=type(e).__name__,
                      duration_ms=duration_ms)
        raise


@functions_framework.http
def health_check(request):
    """Simple health check endpoint."""
    return {"status": "healthy"}, 200
