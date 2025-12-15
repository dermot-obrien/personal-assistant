"""
Republish Events Cloud Function

Publishes Pub/Sub events for existing transcripts in GCS.
Used to trigger downstream processing (task-extractor, audio-archive)
without re-fetching transcripts from Otter.ai.

Triggered by: HTTP request (manual or scheduled)
Output: Pub/Sub events for each transcript
"""

import json
import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import functions_framework
from google.cloud import storage, pubsub_v1

# Local timezone (configurable via LOCAL_TIMEZONE env var)
LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "Pacific/Auckland"))


def log_structured(severity: str, message: str, **kwargs):
    """Output structured JSON log for Cloud Logging."""
    log_entry = {
        "severity": severity,
        "message": message,
        "component": "republish-events",
        **kwargs
    }
    print(json.dumps(log_entry))


def publish_transcript_event(
    publisher: pubsub_v1.PublisherClient,
    topic_path: str,
    bucket_name: str,
    blob_path: str,
    transcript_data: dict
) -> bool:
    """Publish a Pub/Sub event for a transcript.

    Returns True if publish was successful.
    """
    try:
        # Extract metadata from transcript
        otter_id = transcript_data.get("otter_id", "unknown")
        title = transcript_data.get("title", "Untitled")
        topic = transcript_data.get("topic", "General")
        created_at = transcript_data.get("created_at", "")
        synced_at = transcript_data.get("synced_at", datetime.now(LOCAL_TIMEZONE).isoformat())

        event_data = {
            "event_type": "transcript.republished",
            "otter_id": otter_id,
            "title": title,
            "topic": topic,
            "gcs_path": f"gs://{bucket_name}/{blob_path}",
            "gcs_bucket": bucket_name,
            "gcs_blob": blob_path,
            "created_at": created_at,
            "synced_at": synced_at,
            "republished_at": datetime.now(LOCAL_TIMEZONE).isoformat()
        }

        message_bytes = json.dumps(event_data).encode("utf-8")
        future = publisher.publish(topic_path, message_bytes)
        future.result()  # Wait for publish to complete

        return True

    except Exception as e:
        log_structured("WARNING", f"Failed to publish event for {blob_path}: {e}",
                      event="publish_error",
                      blob_path=blob_path,
                      error=str(e))
        return False


def list_transcripts(bucket: storage.Bucket, prefix: str = "transcripts/") -> list:
    """List all transcript blobs in the bucket."""
    blobs = bucket.list_blobs(prefix=prefix)
    return [blob for blob in blobs if blob.name.endswith(".json")]


def filter_transcripts(
    blobs: list,
    after_date: Optional[str] = None,
    before_date: Optional[str] = None,
    topic_filter: Optional[str] = None,
    limit: Optional[int] = None
) -> list:
    """Filter transcripts by date range and topic.

    Args:
        blobs: List of storage blobs
        after_date: Only include transcripts created after this date (YYYY-MM-DD)
        before_date: Only include transcripts created before this date (YYYY-MM-DD)
        topic_filter: Only include transcripts matching this topic (substring match)
        limit: Maximum number of transcripts to process

    Returns:
        Filtered list of blobs
    """
    filtered = []

    for blob in blobs:
        # Extract date from filename (format: YYYY-MM-DD_HH-MM_title_id.json)
        filename = blob.name.split("/")[-1]
        try:
            file_date = filename[:10]  # YYYY-MM-DD

            if after_date and file_date < after_date:
                continue
            if before_date and file_date > before_date:
                continue

        except (IndexError, ValueError):
            # If we can't parse the date, include it
            pass

        # Topic filter requires reading the file, so we'll do it later if needed
        filtered.append(blob)

        if limit and len(filtered) >= limit:
            break

    return filtered


@functions_framework.http
def republish_events(request):
    """
    HTTP Cloud Function to republish events for existing transcripts.

    Query parameters:
    - after: Only process transcripts after this date (YYYY-MM-DD)
    - before: Only process transcripts before this date (YYYY-MM-DD)
    - topic: Only process transcripts matching this topic (substring)
    - limit: Maximum number of transcripts to process
    - dry_run: If "true", list transcripts but don't publish events
    - transcript_id: Process only this specific transcript ID

    Environment variables required:
    - GCS_BUCKET: GCS bucket containing transcripts
    - PUBSUB_TOPIC: Pub/Sub topic to publish events to
    """
    start_time = datetime.now(LOCAL_TIMEZONE)

    # Get query parameters
    after_date = request.args.get("after")
    before_date = request.args.get("before")
    topic_filter = request.args.get("topic")
    limit = request.args.get("limit")
    dry_run = request.args.get("dry_run", "").lower() == "true"
    transcript_id = request.args.get("transcript_id")

    if limit:
        try:
            limit = int(limit)
        except ValueError:
            return {"error": "Invalid limit parameter"}, 400

    log_structured("INFO", "Starting republish events",
                  event="republish_started",
                  after_date=after_date,
                  before_date=before_date,
                  topic_filter=topic_filter,
                  limit=limit,
                  dry_run=dry_run,
                  transcript_id=transcript_id)

    # Get configuration
    bucket_name = os.environ.get("GCS_BUCKET")
    pubsub_topic = os.environ.get("PUBSUB_TOPIC")
    project_id = os.environ.get("GCP_PROJECT")

    if not bucket_name:
        return {"error": "GCS_BUCKET environment variable required"}, 500

    if not pubsub_topic and not dry_run:
        return {"error": "PUBSUB_TOPIC environment variable required"}, 500

    try:
        # Initialize clients
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)

        publisher = None
        topic_path = None
        if not dry_run:
            publisher = pubsub_v1.PublisherClient()
            topic_path = publisher.topic_path(project_id, pubsub_topic)

        # List and filter transcripts
        log_structured("INFO", "Listing transcripts",
                      event="listing_transcripts")

        all_blobs = list_transcripts(bucket)

        # If specific transcript_id requested, filter to just that one
        if transcript_id:
            all_blobs = [b for b in all_blobs if transcript_id in b.name]

        filtered_blobs = filter_transcripts(
            all_blobs,
            after_date=after_date,
            before_date=before_date,
            topic_filter=topic_filter,
            limit=limit
        )

        log_structured("INFO", f"Found {len(filtered_blobs)} transcripts to process",
                      event="transcripts_found",
                      total_count=len(all_blobs),
                      filtered_count=len(filtered_blobs))

        # Process each transcript
        published = []
        skipped = []
        errors = []

        for blob in filtered_blobs:
            try:
                # Download and parse transcript
                content = blob.download_as_text()
                transcript_data = json.loads(content)

                # Apply topic filter if specified
                if topic_filter:
                    transcript_topic = transcript_data.get("topic", "")
                    if topic_filter.lower() not in transcript_topic.lower():
                        skipped.append({
                            "path": blob.name,
                            "reason": f"Topic '{transcript_topic}' doesn't match filter '{topic_filter}'"
                        })
                        continue

                if dry_run:
                    published.append({
                        "path": blob.name,
                        "otter_id": transcript_data.get("otter_id"),
                        "title": transcript_data.get("title"),
                        "topic": transcript_data.get("topic"),
                        "created_at": transcript_data.get("created_at")
                    })
                else:
                    # Publish event
                    success = publish_transcript_event(
                        publisher, topic_path, bucket_name, blob.name, transcript_data
                    )

                    if success:
                        published.append({
                            "path": blob.name,
                            "otter_id": transcript_data.get("otter_id"),
                            "title": transcript_data.get("title")
                        })
                    else:
                        errors.append({
                            "path": blob.name,
                            "error": "Publish failed"
                        })

            except Exception as e:
                errors.append({
                    "path": blob.name,
                    "error": str(e)
                })

        duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)

        result = {
            "status": "success",
            "dry_run": dry_run,
            "total_transcripts": len(all_blobs),
            "processed": len(published),
            "skipped": len(skipped),
            "errors": len(errors),
            "duration_ms": duration_ms,
            "published": published,
            "skipped_details": skipped if skipped else None,
            "error_details": errors if errors else None
        }

        log_structured("INFO", f"Republish complete: {len(published)} events published",
                      event="republish_completed",
                      published_count=len(published),
                      skipped_count=len(skipped),
                      error_count=len(errors),
                      duration_ms=duration_ms)

        return result, 200

    except Exception as e:
        duration_ms = int((datetime.now(LOCAL_TIMEZONE) - start_time).total_seconds() * 1000)
        log_structured("ERROR", f"Republish failed: {e}",
                      event="republish_failed",
                      error=str(e),
                      error_type=type(e).__name__,
                      duration_ms=duration_ms)
        return {"error": str(e)}, 500


@functions_framework.http
def health_check(request):
    """Simple health check endpoint."""
    return {"status": "healthy"}, 200
