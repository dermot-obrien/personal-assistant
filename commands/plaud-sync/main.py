"""
Cloud Function to sync Plaud Note transcripts to Google Cloud Storage.

Checks for new Plaud recordings and copies transcripts to GCS.
Triggered by Cloud Scheduler (recommended: every 30 minutes).

NOTE: Plaud doesn't have an official API for accessing your recordings yet.
This uses the web app's internal API which requires a session token.
You'll need to extract the token from your browser after logging in.
"""

import json
import os
from datetime import datetime
from typing import Optional

import functions_framework
import requests
from google.cloud import storage, secretmanager


class PlaudClient:
    """
    Unofficial Plaud web API client.

    Uses the internal API that powers web.plaud.ai.
    Requires a session token extracted from browser cookies/localStorage.
    """

    BASE_URL = "https://api.plaud.ai"
    WEB_BASE_URL = "https://web.plaud.ai"

    def __init__(self, access_token: str):
        """
        Initialize with access token from Plaud web app.

        To get the token:
        1. Login to web.plaud.ai
        2. Open browser DevTools (F12)
        3. Go to Application > Local Storage > web.plaud.ai
        4. Copy the 'access_token' or 'token' value

        OR from Network tab:
        1. Make any action on the page
        2. Find a request to api.plaud.ai
        3. Copy the Authorization header value (without 'Bearer ')
        """
        self.access_token = access_token
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": self.WEB_BASE_URL,
            "Referer": f"{self.WEB_BASE_URL}/",
        })

    def get_recordings(self, page: int = 1, page_size: int = 500) -> dict:
        """
        Get list of recordings/files.

        Returns dict with 'files' list and pagination info.
        """
        # Try different possible endpoint patterns
        endpoints = [
            f"{self.BASE_URL}/apis/files",
            f"{self.BASE_URL}/apis/v1/files",
            f"{self.BASE_URL}/files",
            f"{self.BASE_URL}/apis/recordings",
        ]

        params = {
            "page": page,
            "page_size": page_size,
            "sort": "created_at",
            "order": "desc"
        }

        last_error = None
        for endpoint in endpoints:
            try:
                response = self.session.get(endpoint, params=params)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 401:
                    raise Exception("Authentication failed - token may be expired")
            except requests.RequestException as e:
                last_error = e
                continue

        raise Exception(f"Failed to get recordings from any endpoint. Last error: {last_error}")

    def get_recording_detail(self, file_id: str) -> dict:
        """Get full recording details including transcript."""
        endpoints = [
            f"{self.BASE_URL}/apis/files/{file_id}",
            f"{self.BASE_URL}/apis/v1/files/{file_id}",
            f"{self.BASE_URL}/files/{file_id}",
        ]

        for endpoint in endpoints:
            try:
                response = self.session.get(endpoint)
                if response.status_code == 200:
                    return response.json()
            except requests.RequestException:
                continue

        raise Exception(f"Failed to get recording detail for {file_id}")

    def get_transcript(self, file_id: str) -> Optional[dict]:
        """Get transcript for a specific recording."""
        endpoints = [
            f"{self.BASE_URL}/apis/files/{file_id}/transcript",
            f"{self.BASE_URL}/apis/v1/files/{file_id}/transcript",
            f"{self.BASE_URL}/apis/files/{file_id}/transcription",
        ]

        for endpoint in endpoints:
            try:
                response = self.session.get(endpoint)
                if response.status_code == 200:
                    return response.json()
            except requests.RequestException:
                continue

        return None

    def get_summary(self, file_id: str) -> Optional[dict]:
        """Get AI summary for a specific recording."""
        endpoints = [
            f"{self.BASE_URL}/apis/files/{file_id}/summary",
            f"{self.BASE_URL}/apis/v1/files/{file_id}/summary",
        ]

        for endpoint in endpoints:
            try:
                response = self.session.get(endpoint)
                if response.status_code == 200:
                    return response.json()
            except requests.RequestException:
                continue

        return None

    def format_transcript(self, recording: dict, transcript: Optional[dict],
                          summary: Optional[dict]) -> str:
        """Format recording data as readable Markdown."""
        lines = []

        # Header
        title = recording.get("title") or recording.get("name") or "Untitled"
        created = recording.get("created_at") or recording.get("createdAt")

        lines.append(f"# {title}")

        if created:
            # Handle various timestamp formats
            try:
                if isinstance(created, (int, float)):
                    # Unix timestamp (seconds or milliseconds)
                    if created > 1e12:
                        created = created / 1000
                    created_dt = datetime.fromtimestamp(created)
                else:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                lines.append(f"**Date:** {created_dt.strftime('%Y-%m-%d %H:%M:%S')}")
            except (ValueError, TypeError):
                lines.append(f"**Date:** {created}")

        duration = recording.get("duration")
        if duration:
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            lines.append(f"**Duration:** {minutes}:{seconds:02d}")

        lines.append("")

        # Summary
        if summary:
            summary_text = summary.get("summary") or summary.get("content") or summary.get("text")
            if summary_text:
                lines.append("## Summary")
                lines.append("")
                lines.append(summary_text)
                lines.append("")

            # Action items if available
            action_items = summary.get("action_items") or summary.get("actionItems")
            if action_items:
                lines.append("## Action Items")
                lines.append("")
                for item in action_items:
                    if isinstance(item, dict):
                        lines.append(f"- {item.get('text', item)}")
                    else:
                        lines.append(f"- {item}")
                lines.append("")

        # Transcript
        lines.append("## Transcript")
        lines.append("")

        if transcript:
            segments = (transcript.get("segments") or
                       transcript.get("transcripts") or
                       transcript.get("data") or
                       [transcript])

            if isinstance(segments, list):
                for segment in segments:
                    if isinstance(segment, dict):
                        speaker = (segment.get("speaker") or
                                  segment.get("speaker_name") or
                                  segment.get("speakerName") or
                                  "Speaker")
                        text = (segment.get("text") or
                               segment.get("transcript") or
                               segment.get("content") or "")
                        start = segment.get("start") or segment.get("start_offset") or 0

                        # Format timestamp
                        if isinstance(start, (int, float)):
                            if start > 1000:  # milliseconds
                                start = start / 1000
                            minutes = int(start // 60)
                            seconds = int(start % 60)
                            timestamp = f"[{minutes:02d}:{seconds:02d}]"
                        else:
                            timestamp = ""

                        lines.append(f"**{speaker}** {timestamp}: {text}")
                    else:
                        lines.append(str(segment))
            else:
                # Plain text transcript
                lines.append(str(segments))
        else:
            # Try to get transcript from recording detail
            transcript_text = (recording.get("transcript") or
                              recording.get("transcription") or
                              recording.get("text"))
            if transcript_text:
                lines.append(transcript_text)
            else:
                lines.append("*Transcript not available*")

        return "\n".join(lines)


def get_secret(secret_id: str, project_id: str) -> str:
    """Retrieve secret from Google Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def get_processed_ids(bucket: storage.Bucket) -> set[str]:
    """Get set of already processed recording IDs from GCS."""
    blob = bucket.blob(".plaud_processed_ids.json")

    if blob.exists():
        content = blob.download_as_text()
        return set(json.loads(content))

    return set()


def save_processed_ids(bucket: storage.Bucket, ids: set[str]) -> None:
    """Save processed recording IDs to GCS."""
    blob = bucket.blob(".plaud_processed_ids.json")
    blob.upload_from_string(
        json.dumps(list(ids)),
        content_type="application/json"
    )


def upload_transcript(bucket: storage.Bucket, recording: dict, transcript: str) -> str:
    """Upload transcript to GCS and return blob path."""
    file_id = recording.get("id") or recording.get("file_id") or "unknown"
    title = recording.get("title") or recording.get("name") or "Untitled"
    created = recording.get("created_at") or recording.get("createdAt")

    # Parse creation date
    try:
        if isinstance(created, (int, float)):
            if created > 1e12:
                created = created / 1000
            created_dt = datetime.fromtimestamp(created)
        elif created:
            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        else:
            created_dt = datetime.now()
    except (ValueError, TypeError):
        created_dt = datetime.now()

    date_str = created_dt.strftime("%Y-%m-%d")

    # Sanitize title for filename
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    safe_title = safe_title[:50].strip()

    blob_path = f"plaud-transcripts/{date_str}_{safe_title}_{file_id}.md"

    blob = bucket.blob(blob_path)
    blob.upload_from_string(transcript, content_type="text/markdown")

    # Store metadata
    blob.metadata = {
        "plaud_id": str(file_id),
        "title": title,
        "created_at": str(created),
        "synced_at": datetime.utcnow().isoformat()
    }
    blob.patch()

    return blob_path


@functions_framework.http
def sync_plaud_transcripts(request):
    """
    HTTP Cloud Function to sync Plaud transcripts to GCS.

    Environment variables required:
    - GCP_PROJECT: Google Cloud project ID
    - GCS_BUCKET: Target GCS bucket name
    - PLAUD_TOKEN_SECRET: Secret Manager secret ID for Plaud access token
    """
    try:
        # Get configuration
        project_id = os.environ.get("GCP_PROJECT")
        bucket_name = os.environ.get("GCS_BUCKET")
        token_secret = os.environ.get("PLAUD_TOKEN_SECRET", "plaud-token")

        if not project_id or not bucket_name:
            return {"error": "Missing required environment variables"}, 500

        # Get access token from Secret Manager
        access_token = get_secret(token_secret, project_id)

        # Initialize clients
        plaud = PlaudClient(access_token)
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)

        # Get processed IDs
        processed_ids = get_processed_ids(bucket)

        # Get recordings
        try:
            recordings_response = plaud.get_recordings(page_size=500)
        except Exception as e:
            return {"error": f"Failed to fetch recordings: {e}"}, 500

        # Extract files list from response
        files = (recordings_response.get("files") or
                recordings_response.get("data") or
                recordings_response.get("recordings") or
                recordings_response.get("items") or
                [])

        if isinstance(recordings_response, list):
            files = recordings_response

        new_count = 0
        synced_recordings = []
        errors = []

        for recording in files:
            file_id = str(recording.get("id") or recording.get("file_id"))

            if not file_id or file_id in processed_ids:
                continue

            try:
                # Get full details
                try:
                    detail = plaud.get_recording_detail(file_id)
                    recording.update(detail)
                except Exception:
                    pass  # Use basic recording info if detail fails

                # Get transcript and summary
                transcript = plaud.get_transcript(file_id)
                summary = plaud.get_summary(file_id)

                # Format and upload
                formatted = plaud.format_transcript(recording, transcript, summary)
                blob_path = upload_transcript(bucket, recording, formatted)

                # Mark as processed
                processed_ids.add(file_id)
                new_count += 1

                synced_recordings.append({
                    "id": file_id,
                    "title": recording.get("title") or recording.get("name"),
                    "path": blob_path
                })

            except Exception as e:
                errors.append({"id": file_id, "error": str(e)})

        # Save updated processed IDs
        save_processed_ids(bucket, processed_ids)

        result = {
            "status": "success",
            "new_transcripts": new_count,
            "total_processed": len(processed_ids),
            "synced": synced_recordings,
        }

        if errors:
            result["errors"] = errors

        print(f"Plaud sync complete: {new_count} new transcripts")

        return result, 200

    except Exception as e:
        print(f"Error syncing Plaud transcripts: {e}")
        return {"error": str(e)}, 500


@functions_framework.http
def health_check(request):
    """Simple health check endpoint."""
    return {"status": "healthy"}, 200
