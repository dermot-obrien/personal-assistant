"""
Audio Archive Cloud Function

Listens to otter-transcript-events Pub/Sub topic and downloads audio files.
Stores audio MP3s in GCS with metadata linking back to transcripts.

Triggered by: Pub/Sub messages from otter-sync function
Output: Audio files saved to GCS in audio/ folder
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
        "component": "audio-archive",
        **kwargs
    }
    print(json.dumps(log_entry))


def get_transcript_content(bucket_name: str, blob_path: str) -> dict:
    """Download and parse transcript JSON from GCS."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    content = blob.download_as_text()
    return json.loads(content)


def get_processed_audio_state(bucket_name: str) -> dict:
    """Load the processed audio state from GCS.

    The state file tracks which transcripts have had their audio archived,
    avoiding the need to scan the audio folder or modify transcript files.

    Returns:
        Dict mapping transcript_id -> audio_blob_path
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(".audio_archive_state.json")

    if blob.exists():
        try:
            content = blob.download_as_text()
            return json.loads(content)
        except Exception as e:
            log_structured("WARNING", f"Failed to load audio archive state: {e}",
                          event="state_load_error", error=str(e))

    return {}


def save_processed_audio_state(bucket_name: str, state: dict) -> None:
    """Save the processed audio state to GCS."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(".audio_archive_state.json")

    blob.upload_from_string(
        json.dumps(state, indent=2, ensure_ascii=False),
        content_type="application/json"
    )


def is_audio_already_archived(bucket_name: str, transcript_id: str, state: dict) -> tuple[bool, Optional[str]]:
    """Check if audio has already been archived for this transcript.

    Uses the audio archive state file for fast lookup.

    Args:
        bucket_name: GCS bucket name
        transcript_id: The Otter transcript ID
        state: The audio archive state dict

    Returns:
        Tuple of (is_archived, existing_path)
    """
    if transcript_id in state:
        existing_path = state[transcript_id]
        # Optionally verify the file still exists
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(existing_path)
        if blob.exists():
            return True, existing_path
        # File was deleted, remove from state
        log_structured("WARNING", f"Audio file missing, will re-archive: {existing_path}",
                      event="audio_file_missing",
                      transcript_id=transcript_id,
                      expected_path=existing_path)

    return False, None


def download_audio(audio_url: str, timeout: int = 300) -> Optional[bytes]:
    """Download audio file from URL.

    Args:
        audio_url: URL to download audio from
        timeout: Request timeout in seconds (default 5 minutes for large files)

    Returns:
        Audio file bytes, or None if download fails
    """
    if not audio_url:
        return None

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "audio/*,*/*",
    }

    try:
        response = requests.get(audio_url, headers=headers, timeout=timeout, stream=True)
        response.raise_for_status()

        # Read the entire response content
        content = response.content
        return content

    except requests.exceptions.RequestException as e:
        log_structured("WARNING", f"Failed to download audio: {e}",
                      event="audio_download_error",
                      audio_url=audio_url[:100],
                      error=str(e))
        return None


def save_audio(
    bucket_name: str,
    transcript_id: str,
    transcript_title: str,
    transcript_topic: str,
    transcript_blob_path: str,
    transcript_created_at: str,
    audio_content: bytes,
    content_type: str = "audio/mpeg"
) -> str:
    """Save audio file to GCS with metadata linking to transcript.

    Returns the blob path where audio was saved.
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    now = datetime.now(LOCAL_TIMEZONE)

    # Parse the original transcript created date for folder organization
    try:
        created_dt = datetime.fromisoformat(transcript_created_at)
        date_str = created_dt.strftime("%Y-%m-%d_%H-%M")
    except (ValueError, TypeError):
        date_str = now.strftime("%Y-%m-%d_%H-%M")

    # Sanitize title for filename
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in transcript_title)
    safe_title = safe_title[:50].strip()

    # Determine file extension from content type
    ext = "mp3"
    if "wav" in content_type:
        ext = "wav"
    elif "m4a" in content_type or "mp4" in content_type:
        ext = "m4a"
    elif "ogg" in content_type:
        ext = "ogg"

    blob_path = f"audio/{date_str}_{safe_title}_{transcript_id}.{ext}"

    blob = bucket.blob(blob_path)
    blob.upload_from_string(
        audio_content,
        content_type=content_type
    )

    # Add metadata linking to transcript
    blob.metadata = {
        "transcript_id": transcript_id,
        "transcript_title": transcript_title,
        "transcript_topic": transcript_topic,
        "transcript_blob_path": transcript_blob_path,
        "transcript_created_at": transcript_created_at,
        "archived_at": now.isoformat(),
        "audio_size_bytes": str(len(audio_content))
    }
    blob.patch()

    return blob_path


def update_transcript_with_audio_path(
    bucket_name: str,
    transcript_blob_path: str,
    audio_blob_path: str
) -> bool:
    """Update transcript JSON with path to archived audio.

    Returns True if update was successful.
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(transcript_blob_path)

    try:
        # Download current transcript
        content = blob.download_as_text()
        transcript_data = json.loads(content)

        # Add audio archive path
        transcript_data["audio_archive_path"] = audio_blob_path
        transcript_data["audio_archived_at"] = datetime.now(LOCAL_TIMEZONE).isoformat()

        # Re-upload with updated data
        blob.upload_from_string(
            json.dumps(transcript_data, indent=2, ensure_ascii=False),
            content_type="application/json"
        )

        # Update blob metadata
        current_metadata = blob.metadata or {}
        current_metadata["audio_archive_path"] = audio_blob_path
        blob.metadata = current_metadata
        blob.patch()

        return True

    except Exception as e:
        log_structured("WARNING", f"Failed to update transcript with audio path: {e}",
                      event="transcript_update_error",
                      transcript_blob_path=transcript_blob_path,
                      error=str(e))
        return False


@functions_framework.cloud_event
def process_transcript_event(cloud_event: CloudEvent):
    """Process incoming Pub/Sub messages about new transcripts.

    Downloads the audio file and stores it in GCS.
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

    log_structured("INFO", f"Processing audio archive for: {event.get('title')}",
                  event="event_received",
                  otter_id=event.get("otter_id"),
                  title=event.get("title"),
                  topic=event.get("topic"))

    # Get configuration
    bucket_name = event.get("gcs_bucket")
    transcript_blob_path = event.get("gcs_blob")

    if not all([bucket_name, transcript_blob_path]):
        log_structured("ERROR", "Missing required configuration",
                      event="config_error",
                      bucket_name=bucket_name,
                      transcript_blob_path=transcript_blob_path)
        return

    try:
        transcript_id = event.get("otter_id", "unknown")

        # Load audio archive state
        audio_state = get_processed_audio_state(bucket_name)

        # Check if audio is already archived using state file
        already_archived, existing_path = is_audio_already_archived(bucket_name, transcript_id, audio_state)
        if already_archived:
            log_structured("INFO", f"Audio already archived at {existing_path}, skipping",
                          event="already_archived",
                          transcript_id=transcript_id,
                          existing_path=existing_path)
            return

        # Download the transcript to get audio URL
        log_structured("INFO", f"Downloading transcript from gs://{bucket_name}/{transcript_blob_path}",
                      event="transcript_download_started")
        transcript = get_transcript_content(bucket_name, transcript_blob_path)

        # Look for audio URL in various possible fields
        audio_url = None
        for field in ["audio_url", "download_url", "audio_download_url", "mp3_url"]:
            audio_url = transcript.get(field)
            if audio_url:
                log_structured("INFO", f"Found audio URL in field: {field}",
                              event="audio_url_found", field=field)
                break

        # Also check _extra_fields
        extra = transcript.get("_extra_fields") or {}
        if not audio_url:
            for field in ["audio_url", "download_url", "audio_download_url", "mp3_url"]:
                audio_url = extra.get(field)
                if audio_url:
                    log_structured("INFO", f"Found audio URL in _extra_fields.{field}",
                                  event="audio_url_found", field=f"_extra_fields.{field}")
                    break

        if not audio_url:
            log_structured("INFO", "No audio URL found in transcript, skipping",
                          event="no_audio_url",
                          transcript_id=transcript_id)
            return

        # Download the audio file
        log_structured("INFO", "Downloading audio file",
                      event="audio_download_started")
        audio_content = download_audio(audio_url)

        if not audio_content:
            log_structured("WARNING", "Failed to download audio file",
                          event="audio_download_failed",
                          transcript_id=event.get("otter_id"))
            return

        audio_size_mb = len(audio_content) / (1024 * 1024)
        log_structured("INFO", f"Downloaded audio file: {audio_size_mb:.2f} MB",
                      event="audio_downloaded",
                      size_bytes=len(audio_content),
                      size_mb=round(audio_size_mb, 2))

        # Determine content type from URL
        content_type = "audio/mpeg"  # Default to MP3
        if ".wav" in audio_url.lower():
            content_type = "audio/wav"
        elif ".m4a" in audio_url.lower():
            content_type = "audio/mp4"
        elif ".ogg" in audio_url.lower():
            content_type = "audio/ogg"

        # Save the audio file
        audio_blob_path = save_audio(
            bucket_name=bucket_name,
            transcript_id=transcript_id,
            transcript_title=event.get("title", "Untitled"),
            transcript_topic=event.get("topic", "General"),
            transcript_blob_path=transcript_blob_path,
            transcript_created_at=event.get("created_at", ""),
            audio_content=audio_content,
            content_type=content_type
        )

        log_structured("INFO", f"Saved audio to: {audio_blob_path}",
                      event="audio_saved",
                      audio_blob_path=audio_blob_path)

        # Update audio archive state
        audio_state[transcript_id] = audio_blob_path
        save_processed_audio_state(bucket_name, audio_state)
        log_structured("INFO", "Updated audio archive state",
                      event="state_updated",
                      transcript_id=transcript_id)

        # Update transcript with audio path for cross-referencing
        update_transcript_with_audio_path(bucket_name, transcript_blob_path, audio_blob_path)

        duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)
        log_structured("INFO", f"Audio archive complete",
                      event="processing_completed",
                      transcript_id=event.get("otter_id"),
                      audio_blob_path=audio_blob_path,
                      audio_size_mb=round(audio_size_mb, 2),
                      duration_ms=duration_ms)

    except Exception as e:
        duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)
        log_structured("ERROR", f"Failed to archive audio: {e}",
                      event="processing_failed",
                      error=str(e),
                      error_type=type(e).__name__,
                      duration_ms=duration_ms)
        raise


@functions_framework.http
def health_check(request):
    """Simple health check endpoint."""
    return {"status": "healthy"}, 200
