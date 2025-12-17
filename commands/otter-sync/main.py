"""
Cloud Function to sync Otter.ai transcripts to Google Cloud Storage.

Checks for new Otter conversations and copies transcripts to GCS.
Triggered by Cloud Scheduler (recommended: every 15-30 minutes).

Observability: Uses OpenTelemetry with native OTLP export to telemetry.googleapis.com
following Google Cloud 2025 best practices.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

# Local timezone for all datetime outputs (configurable via LOCAL_TIMEZONE env var)
# Defaults to Pacific/Auckland (New Zealand)
LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "Pacific/Auckland"))

import functions_framework
import requests
from google.cloud import storage, secretmanager, pubsub_v1

# OpenTelemetry imports for tracing (2025 best practices)
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.trace import Status, StatusCode
import google.auth
import google.auth.transport.grpc
import google.auth.transport.requests
import grpc
from google.auth.transport.grpc import AuthMetadataPlugin

# Set up structured logging for Cloud Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global tracer - initialized once per cold start
_tracer: Optional[trace.Tracer] = None


def setup_opentelemetry() -> trace.Tracer:
    """
    Initialize OpenTelemetry with OTLP export to Google Cloud Trace.

    Uses the native telemetry.googleapis.com endpoint (2025 best practice)
    which provides better performance and higher limits than the legacy exporter.
    """
    global _tracer
    if _tracer is not None:
        return _tracer

    project_id = os.environ.get("GCP_PROJECT", "")

    # Create resource with service identification
    resource = Resource.create(
        attributes={
            SERVICE_NAME: "otter-sync",
            SERVICE_VERSION: "1.0.0",
            "gcp.project_id": project_id,
            "service.instance.id": f"worker-{os.getpid()}",
        }
    )

    # Set up authenticated gRPC channel for telemetry.googleapis.com
    try:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        request = google.auth.transport.requests.Request()
        auth_metadata_plugin = AuthMetadataPlugin(credentials=credentials, request=request)
        channel_creds = grpc.composite_channel_credentials(
            grpc.ssl_channel_credentials(),
            grpc.metadata_call_credentials(auth_metadata_plugin),
        )

        # Create OTLP exporter pointing to Google Cloud's native endpoint
        exporter = OTLPSpanExporter(
            endpoint="telemetry.googleapis.com:443",
            credentials=channel_creds,
        )
    except Exception as e:
        # Fallback: use insecure exporter for local development
        log_structured("WARNING", f"Failed to set up authenticated OTLP exporter: {e}",
                       event="otel_auth_fallback")
        exporter = OTLPSpanExporter(
            endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317"),
            insecure=True,
        )

    # Configure tracer provider
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(tracer_provider)

    # Auto-instrument the requests library for Otter API calls
    RequestsInstrumentor().instrument()

    _tracer = trace.get_tracer("otter-sync", "1.0.0")
    log_structured("INFO", "OpenTelemetry initialized", event="otel_initialized")
    return _tracer


def get_tracer() -> trace.Tracer:
    """Get or initialize the OpenTelemetry tracer."""
    global _tracer
    if _tracer is None:
        return setup_opentelemetry()
    return _tracer


def log_structured(severity: str, message: str, **kwargs) -> None:
    """
    Log a structured message for Cloud Logging.

    In Cloud Functions gen2, JSON-formatted logs with specific fields
    are automatically parsed by Cloud Logging for better querying.

    Includes trace context when available for log-trace correlation.
    """
    log_entry = {
        "severity": severity,
        "message": message,
        "component": "otter-sync",
        **kwargs
    }

    # Add trace context for log correlation (if span is active)
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        ctx = current_span.get_span_context()
        if ctx.is_valid:
            project_id = os.environ.get("GCP_PROJECT", "")
            log_entry["logging.googleapis.com/trace"] = (
                f"projects/{project_id}/traces/{format(ctx.trace_id, '032x')}"
            )
            log_entry["logging.googleapis.com/spanId"] = format(ctx.span_id, '016x')
            log_entry["logging.googleapis.com/trace_sampled"] = ctx.trace_flags.sampled

    print(json.dumps(log_entry))


class OtterClient:
    """Unofficial Otter.ai API client."""

    BASE_URL = "https://otter.ai/forward/api/v1"

    # Browser-like headers required by Otter.ai API
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://otter.ai/",
        "Origin": "https://otter.ai",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.session = requests.Session()
        # Set default headers for all requests in this session
        self.session.headers.update(self.DEFAULT_HEADERS)
        self.user_id: Optional[str] = None
        self._authenticated = False

    def authenticate(self) -> bool:
        """Login to Otter.ai and establish session."""
        login_url = f"{self.BASE_URL}/login"

        # Use HTTP Basic Auth with GET request (per working otterai-api library)
        self.session.auth = (self.email, self.password)

        response = self.session.get(
            login_url,
            params={"username": self.email}
        )

        if response.status_code == 200:
            data = response.json()
            self.user_id = data.get("userid")
            self._authenticated = True
            return True

        raise Exception(f"Otter authentication failed: {response.status_code} - {response.text}")

    def get_folders(self) -> list[dict]:
        """Get list of all folders."""
        if not self._authenticated:
            self.authenticate()

        url = f"{self.BASE_URL}/folders"
        params = {"userid": self.user_id}

        response = self.session.get(url, params=params)

        if response.status_code == 200:
            return response.json().get("folders", [])

        raise Exception(f"Failed to get folders: {response.status_code}")

    def get_folder_speech_mapping(self) -> dict[str, str]:
        """Build a mapping of speech_id -> folder_name for all folders.

        Returns a dict where keys are speech otids and values are folder names.
        Speeches not in any folder will not be in this mapping (use 'General' as default).
        """
        if not self._authenticated:
            self.authenticate()

        folder_map = {}
        folders = self.get_folders()

        for folder in folders:
            folder_id = folder.get("id")
            folder_name = folder.get("folder_name", "Unknown")

            # Get all speeches in this folder
            url = f"{self.BASE_URL}/speeches"
            params = {
                "userid": self.user_id,
                "folder_id": folder_id,
                "page_size": 500,  # Get all speeches in folder
                "source": "owned",
            }

            response = self.session.get(url, params=params)
            if response.status_code == 200:
                speeches = response.json().get("speeches", [])
                for speech in speeches:
                    speech_id = speech.get("otid") or speech.get("id")
                    if speech_id:
                        folder_map[speech_id] = folder_name

        return folder_map

    def get_speeches(self, page_size: int = 500, fetch_all: bool = True) -> list[dict]:
        """
        Get list of speeches/conversations.

        Args:
            page_size: Number of speeches per API request. Default 500 to fetch all in one request.
                       The Otter API doesn't support proper cursor-based pagination, so use a large
                       page_size to get all speeches. Max tested: 1000.
            fetch_all: If True, attempt to paginate (though Otter API pagination is unreliable).

        Returns:
            List of speech metadata dictionaries
        """
        if not self._authenticated:
            self.authenticate()

        url = f"{self.BASE_URL}/speeches"
        all_speeches = []
        end_cursor = None
        page_num = 0

        while True:
            page_num += 1
            params = {
                "userid": self.user_id,
                "page_size": page_size,
                "source": "owned",
            }
            if end_cursor:
                params["end_cursor"] = end_cursor

            response = self.session.get(url, params=params)

            if response.status_code != 200:
                raise Exception(f"Failed to get speeches: {response.status_code}")

            data = response.json()
            speeches = data.get("speeches", [])
            all_speeches.extend(speeches)

            # Log pagination info for debugging
            log_structured("DEBUG", f"Fetched page {page_num}: {len(speeches)} speeches",
                          event="pagination_debug",
                          page=page_num,
                          speeches_in_page=len(speeches),
                          total_so_far=len(all_speeches),
                          end_cursor=data.get("end_cursor"),
                          has_more=data.get("has_more"),
                          response_keys=list(data.keys()))

            # Check if we should continue paginating
            if not fetch_all:
                break

            # Check for more pages using multiple indicators
            end_cursor = data.get("end_cursor")
            has_more = data.get("has_more", False)

            # Stop if no more data indicators
            if not end_cursor and not has_more:
                break

            # Stop if we got fewer results than requested (last page)
            if len(speeches) < page_size and not has_more:
                break

            # Safety limit to prevent infinite loops
            if page_num >= 50:
                log_structured("WARNING", f"Pagination safety limit reached at {page_num} pages",
                              event="pagination_limit",
                              total_speeches=len(all_speeches))
                break

        log_structured("INFO", f"Fetched {len(all_speeches)} total speeches in {page_num} page(s)",
                      event="speeches_fetched",
                      total=len(all_speeches),
                      pages=page_num)

        return all_speeches

    def get_speech(self, speech_id: str) -> dict:
        """Get full speech details including transcript."""
        if not self._authenticated:
            self.authenticate()

        url = f"{self.BASE_URL}/speech"
        params = {
            "userid": self.user_id,
            "otid": speech_id,
        }

        response = self.session.get(url, params=params)

        if response.status_code == 200:
            data = response.json()
            speech = data.get("speech") or data
            if not speech:
                raise Exception(f"Empty speech data returned for {speech_id}")
            return speech

        raise Exception(f"Failed to get speech {speech_id}: {response.status_code}")

    def _safe_get(self, data: dict, key: str, default=None):
        """Safely get a field from dict, returning default if missing or on error."""
        try:
            return data.get(key, default)
        except Exception:
            return default

    def _sanitize_text(self, text: str) -> str:
        """Sanitize text to remove problematic characters for JSON.

        Removes control characters and ensures valid UTF-8 encoding.
        """
        if not text:
            return ""
        try:
            # Remove control characters except newlines and tabs
            import re
            # Remove ASCII control chars (0x00-0x1F) except tab (0x09), newline (0x0A), carriage return (0x0D)
            sanitized = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
            # Ensure valid UTF-8 by encoding and decoding
            sanitized = sanitized.encode('utf-8', errors='replace').decode('utf-8')
            return sanitized
        except Exception:
            return str(text)

    def _parse_speech_outline(self, outline) -> Optional[list]:
        """Parse speech_outline which may be a string repr of a list or an actual list.

        Otter sometimes returns speech_outline as a Python-style string representation
        (with single quotes) instead of proper JSON. This method handles both cases.
        """
        if not outline:
            return None
        # Already a list - return as-is
        if isinstance(outline, list):
            return outline
        # It's a string - try to parse it
        if isinstance(outline, str):
            try:
                # First try standard JSON parsing
                return json.loads(outline)
            except json.JSONDecodeError:
                try:
                    # Try Python literal eval for single-quoted strings
                    import ast
                    parsed = ast.literal_eval(outline)
                    if isinstance(parsed, list):
                        return parsed
                except (ValueError, SyntaxError):
                    pass
            # If all parsing fails, return None (don't store malformed data)
            return None
        return None

    def _safe_timestamp(self, unix_seconds) -> Optional[str]:
        """Safely convert unix timestamp (seconds) to ISO format string in NZ timezone."""
        try:
            if unix_seconds and isinstance(unix_seconds, (int, float)) and unix_seconds > 0:
                # Convert UTC timestamp to NZ local time
                utc_dt = datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
                nz_dt = utc_dt.astimezone(LOCAL_TIMEZONE)
                return nz_dt.isoformat()
        except Exception:
            pass
        return None

    def format_transcript_json(self, speech: dict, folder_name: str = "General") -> dict:
        """Format speech transcript as structured JSON data with all Otter fields.

        Args:
            speech: The speech data from Otter API
            folder_name: The folder name this speech belongs to (default: "General")

        Future-proof: handles missing/changed fields gracefully and captures
        any new fields not explicitly mapped.
        """
        # Guard against None speech data
        if not speech:
            raise ValueError("Speech data is None or empty")
        if not isinstance(speech, dict):
            raise ValueError(f"Speech data is not a dict, got {type(speech).__name__}")

        # Known fields we explicitly extract (for tracking what's captured)
        known_fields = {
            "otid", "id", "speech_id", "meeting_otid",
            "title", "summary", "short_abstract_summary", "speech_outline",
            "created_at", "start_time", "end_time", "duration", "timezone",
            "language", "speakers", "owner", "folder",
            "process_finished", "process_status", "is_low_confidence",
            "shared_emails", "shared_groups", "public_share_url", "link_share",
            "create_method", "audio_enabled", "hasPhotos", "image_urls",
            "transcripts", "word_clouds", "action_item_count",
            "calendar_meeting_id", "calendar_guests",
            "is_meeting_series", "has_meeting_series_access",
            # Fields we intentionally skip (internal/auth/UI-specific)
            "access_request", "access_seconds", "access_status", "appid",
            "auto_record", "auto_snapshot_enabled", "block_summary_display",
            "block_transcript_display", "can_comment", "can_edit", "can_export",
            "can_highlight", "chat_status", "conf_image_url", "conf_join_url",
            "deleted", "displayed_start_time", "download_url", "first_shared_group_name",
            "from_shared", "has_started", "images", "is_read", "live_status",
            "live_status_message", "modified_time", "non_member_shared_groups",
            "permissions", "process_failed", "public_view", "pubsub_jwt",
            "pubsub_jwt_persistent", "sales_call_qualified", "shared_by",
            "shared_with", "speech_metadata", "speech_outline_status",
            "speech_settings", "timecode_offset", "transcript_updated_at",
            "unshared", "upload_finished", "current_oa_status",
            "can_be_stopped_by_non_owner", "who_can_stop_OA",
        }

        # Otter timestamps are in seconds (not milliseconds)
        created = self._safe_get(speech, "created_at", 0)
        start_time = self._safe_get(speech, "start_time", 0)
        end_time = self._safe_get(speech, "end_time", 0)

        # Build speaker ID to name lookup map
        # Otter's speakers field contains: [{"id": "...", "speaker_name": "John", ...}, ...]
        # Map both string and numeric versions of speaker IDs for robust lookup
        speaker_map = {}
        try:
            speakers_list = self._safe_get(speech, "speakers", [])
            # Ensure speakers_list is iterable (could be None or non-list)
            if not speakers_list or not isinstance(speakers_list, (list, tuple)):
                speakers_list = []
            for speaker in speakers_list:
                if not isinstance(speaker, dict):
                    continue
                # Try multiple ID field names
                speaker_id = speaker.get("id") or speaker.get("speaker_id") or speaker.get("speakerId")
                # Try multiple name field names
                speaker_name = speaker.get("speaker_name") or speaker.get("speakerName") or speaker.get("name")
                if speaker_id is not None and speaker_name:
                    # Store both string and original type for lookup flexibility
                    speaker_map[speaker_id] = speaker_name
                    speaker_map[str(speaker_id)] = speaker_name
        except Exception:
            pass

        # Build transcript segments with error handling
        segments = []
        try:
            transcripts = self._safe_get(speech, "transcripts", [])
            # Ensure transcripts is iterable (could be None or non-list)
            if not transcripts or not isinstance(transcripts, (list, tuple)):
                transcripts = []
            for segment in transcripts:
                if not isinstance(segment, dict):
                    continue
                try:
                    start_offset = segment.get("start_offset", 0) or 0
                    end_offset = segment.get("end_offset", start_offset) or start_offset

                    # Get speaker ID from segment (try multiple field names)
                    speaker_id = segment.get("speaker_id") or segment.get("speakerId") or segment.get("sid")

                    # Resolve speaker name from map
                    speaker_name = None
                    if speaker_id is not None:
                        # Try both original type and string version
                        speaker_name = speaker_map.get(speaker_id) or speaker_map.get(str(speaker_id))

                    # Fallback to direct speaker_name field on segment
                    if not speaker_name:
                        speaker_name = segment.get("speaker_name") or segment.get("speakerName") or "Speaker"

                    segments.append({
                        "speaker": speaker_name,
                        "speaker_id": speaker_id,
                        "text": self._sanitize_text(segment.get("transcript", "")),
                        "start_seconds": start_offset / 1000,
                        "end_seconds": end_offset / 1000,
                        "start_offset_ms": start_offset,
                        "end_offset_ms": end_offset,
                    })
                except Exception:
                    # Skip malformed segments
                    continue
        except Exception:
            segments = []

        # Capture any new/unknown fields from Otter API
        extra_fields = {}
        try:
            if speech and hasattr(speech, 'items'):
                for key, value in speech.items():
                    if key not in known_fields:
                        # Store unknown fields for future compatibility
                        extra_fields[key] = value
        except (TypeError, AttributeError):
            pass

        result = {
            # Core identifiers
            "otter_id": self._safe_get(speech, "otid") or self._safe_get(speech, "id"),
            "speech_id": self._safe_get(speech, "speech_id"),
            "meeting_otid": self._safe_get(speech, "meeting_otid"),

            # Topic/folder - use folder_name parameter (derived from folder mapping)
            "topic": folder_name,

            # Title and content (sanitized to remove control characters)
            "title": self._sanitize_text(self._safe_get(speech, "title", "Untitled")),
            "summary": self._sanitize_text(self._safe_get(speech, "summary") or ""),
            "short_abstract_summary": self._sanitize_text(self._safe_get(speech, "short_abstract_summary") or ""),
            "speech_outline": self._parse_speech_outline(self._safe_get(speech, "speech_outline")),

            # Timestamps (both ISO format and unix) - all in local timezone
            "created_at": self._safe_timestamp(created) or datetime.now(LOCAL_TIMEZONE).isoformat(),
            "created_at_unix": created,
            "start_time": self._safe_timestamp(start_time),
            "start_time_unix": start_time,
            "end_time": self._safe_timestamp(end_time),
            "end_time_unix": end_time,
            "duration": self._safe_get(speech, "duration"),
            "timezone": self._safe_get(speech, "timezone"),

            # Meeting metadata
            "language": self._safe_get(speech, "language"),
            "speakers_raw": self._safe_get(speech, "speakers", []),
            "owner": self._safe_get(speech, "owner"),
            "folder": self._safe_get(speech, "folder"),

            # Conversation speakers - cleaned up list of participants
            "speakers": [
                {
                    "id": speaker_map_id,
                    "name": speaker_map_name,
                }
                for speaker_map_id, speaker_map_name in (speaker_map.items() if speaker_map else [])
            ] if speaker_map else [],
            "speaker_names": list(speaker_map.values()) if speaker_map else [],
            "speaker_count": len(speaker_map) if speaker_map else 0,

            # Processing status
            "process_finished": self._safe_get(speech, "process_finished"),
            "process_status": self._safe_get(speech, "process_status"),
            "is_low_confidence": self._safe_get(speech, "is_low_confidence"),

            # Sharing and access
            "shared_emails": self._safe_get(speech, "shared_emails"),
            "shared_groups": self._safe_get(speech, "shared_groups"),
            "public_share_url": self._safe_get(speech, "public_share_url"),
            "link_share": self._safe_get(speech, "link_share"),

            # Recording source
            "create_method": self._safe_get(speech, "create_method"),
            "audio_enabled": self._safe_get(speech, "audio_enabled"),
            "hasPhotos": self._safe_get(speech, "hasPhotos"),
            "image_urls": self._safe_get(speech, "image_urls"),

            # Transcript data
            "segments": segments,
            "segment_count": len(segments),
            # Full transcript as single text (all segments combined)
            "full_text": "\n\n".join(
                f"{seg['speaker']}: {seg['text']}" for seg in segments if seg.get('text')
            ),

            # Word clouds and action items
            "word_clouds": self._safe_get(speech, "word_clouds"),
            "action_item_count": self._safe_get(speech, "action_item_count"),

            # Calendar integration
            "calendar_meeting_id": self._safe_get(speech, "calendar_meeting_id"),
            "calendar_guests": self._safe_get(speech, "calendar_guests"),

            # Misc metadata
            "is_meeting_series": self._safe_get(speech, "is_meeting_series"),
            "has_meeting_series_access": self._safe_get(speech, "has_meeting_series_access"),

            # New/unknown fields from Otter API (future-proofing)
            "_extra_fields": extra_fields if extra_fields else None,
        }

        return result


def get_secret(secret_id: str, project_id: str) -> str:
    """Retrieve secret from Google Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def get_processed_ids(bucket: storage.Bucket) -> set[str]:
    """Get set of already processed speech IDs from GCS."""
    blob = bucket.blob(".processed_ids.json")

    if blob.exists():
        content = blob.download_as_text()
        return set(json.loads(content))

    return set()


def save_processed_ids(bucket: storage.Bucket, ids: set[str]) -> None:
    """Save processed speech IDs to GCS."""
    blob = bucket.blob(".processed_ids.json")
    blob.upload_from_string(
        json.dumps(list(ids)),
        content_type="application/json"
    )


def get_topic_mapping(bucket: storage.Bucket) -> dict:
    """Load topic mapping from GCS bucket.

    The mapping file (otter_topic_mapping.json) maps Otter folder names to hierarchical topic paths.

    Example file contents:
    {
        "_default_topic": "General",
        "mappings": {
            "Daily Journal": "Personal/Journal",
            "Northpower": "Work/Northpower"
        }
    }

    Returns a dict with 'default' and 'mappings' keys.
    """
    blob = bucket.blob("otter_topic_mapping.json")

    if blob.exists():
        try:
            content = blob.download_as_text()
            data = json.loads(content)
            return {
                "default": data.get("_default_topic", "General"),
                "mappings": data.get("mappings", {})
            }
        except Exception as e:
            log_structured("WARNING", f"Failed to load topic mapping: {e}",
                          event="topic_mapping_error", error=str(e))

    # Return empty mapping if file doesn't exist or fails to load
    return {"default": "General", "mappings": {}}


def resolve_topic(folder_name: str, topic_mapping: dict) -> str:
    """Resolve Otter folder name to hierarchical topic path.

    Args:
        folder_name: The Otter folder name (or "General" if not in a folder)
        topic_mapping: Dict with 'default' and 'mappings' keys

    Returns:
        The mapped topic path, or the original folder name if no mapping exists
    """
    mappings = topic_mapping.get("mappings", {})
    default = topic_mapping.get("default", "General")

    # If folder_name is in mappings, use the mapped value
    if folder_name in mappings:
        return mappings[folder_name]

    # If folder_name is "General" (not in any Otter folder), use default
    if folder_name == "General":
        return default

    # Otherwise, return the folder name as-is (unmapped folders keep their name)
    return folder_name


def publish_transcript_event(
    project_id: str,
    topic_id: str,
    speech: dict,
    bucket_name: str,
    blob_path: str,
    topic: str = "General"
) -> None:
    """Publish a Pub/Sub event for a new transcript."""
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project_id, topic_id)

    speech_id = speech.get("id", "unknown")
    title = speech.get("title", "Untitled")
    created_at = speech.get("created_at", 0)

    # Convert timestamps to local timezone (Otter uses seconds, not milliseconds)
    if created_at:
        utc_dt = datetime.fromtimestamp(created_at, tz=timezone.utc)
        created_dt = utc_dt.astimezone(LOCAL_TIMEZONE)
    else:
        created_dt = datetime.now(LOCAL_TIMEZONE)
    synced_dt = datetime.now(LOCAL_TIMEZONE)

    event_data = {
        "event_type": "transcript.created",
        "otter_id": speech_id,
        "title": title,
        "topic": topic,
        "gcs_path": f"gs://{bucket_name}/{blob_path}",
        "gcs_bucket": bucket_name,
        "gcs_blob": blob_path,
        "created_at": created_dt.isoformat(),
        "synced_at": synced_dt.isoformat()
    }

    message_bytes = json.dumps(event_data).encode("utf-8")
    future = publisher.publish(topic_path, message_bytes)
    future.result()  # Wait for publish to complete

    print(f"Published event for transcript: {speech_id}")


def upload_transcript(bucket: storage.Bucket, speech: dict, transcript_data: dict) -> str:
    """Upload transcript as JSON to GCS and return blob path."""
    speech_id = speech.get("otid") or speech.get("id", "unknown")
    title = speech.get("title", "Untitled")
    created = speech.get("created_at", 0)

    # Create filename: YYYY-MM-DD_HH-MM_title_id.json (with time for better sorting)
    # Otter timestamps are in seconds - convert to NZ timezone
    if created:
        utc_dt = datetime.fromtimestamp(created, tz=timezone.utc)
        created_dt = utc_dt.astimezone(LOCAL_TIMEZONE)
    else:
        created_dt = datetime.now(LOCAL_TIMEZONE)
    datetime_str = created_dt.strftime("%Y-%m-%d_%H-%M")

    # Sanitize title for filename
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
    safe_title = safe_title[:50].strip()

    blob_path = f"transcripts/{datetime_str}_{safe_title}_{speech_id}.json"

    # Add sync metadata to transcript data (NZ timezone)
    transcript_data["synced_at"] = datetime.now(LOCAL_TIMEZONE).isoformat()

    log_structured("INFO", f"Uploading transcript to GCS: {blob_path}",
                   event="gcs_upload_start",
                   blob_path=blob_path,
                   bucket=bucket.name,
                   speech_id=str(speech_id),
                   title=title)

    blob = bucket.blob(blob_path)
    blob.upload_from_string(
        json.dumps(transcript_data, indent=2, ensure_ascii=False),
        content_type="application/json"
    )

    log_structured("INFO", f"Successfully uploaded to GCS: gs://{bucket.name}/{blob_path}",
                   event="gcs_upload_complete",
                   gcs_uri=f"gs://{bucket.name}/{blob_path}")

    # Store metadata on blob for easy viewing in GCS console
    blob.metadata = {
        "otter_id": speech_id,
        "otter_title": title,
        "topic": transcript_data.get("topic", "General"),
        "created_at": created_dt.isoformat(),
        "created_at_unix": str(created) if created else "",
        "synced_at": transcript_data["synced_at"]
    }
    blob.patch()

    return blob_path


@functions_framework.http
def sync_otter_transcripts(request):
    """
    HTTP Cloud Function to sync Otter.ai transcripts to GCS.

    Environment variables required:
    - GCP_PROJECT: Google Cloud project ID
    - GCS_BUCKET: Target GCS bucket name
    - OTTER_EMAIL_SECRET: Secret Manager secret ID for Otter email
    - OTTER_PASSWORD_SECRET: Secret Manager secret ID for Otter password
    - PUBSUB_TOPIC: (Optional) Pub/Sub topic ID for transcript events

    Optional request body (JSON):
    - page_size: Number of speeches to fetch (default: 500, to get all speeches)
    - force_latest: Re-process the most recent conversation (default: false)
    """
    # Initialize OpenTelemetry tracer
    tracer = get_tracer()

    # Start root span for the entire sync operation
    with tracer.start_as_current_span(
        "sync_otter_transcripts",
        kind=trace.SpanKind.SERVER,
    ) as root_span:
        start_time = time.time()

        try:
            # Parse request body for optional parameters
            request_data = {}
            try:
                request_data = request.get_json(silent=True) or {}
            except Exception:
                pass

            page_size = request_data.get("page_size", 500)
            force_latest = request_data.get("force_latest", False)

            # Get configuration
            project_id = os.environ.get("GCP_PROJECT")
            bucket_name = os.environ.get("GCS_BUCKET")
            email_secret = os.environ.get("OTTER_EMAIL_SECRET", "otter-email")
            password_secret = os.environ.get("OTTER_PASSWORD_SECRET", "otter-password")
            pubsub_topic = os.environ.get("PUBSUB_TOPIC")

            log_structured("INFO", "========== OTTER SYNC STARTED (HTTP) ==========",
                           event="sync_started",
                           trigger="http",
                           config={
                               "project_id": project_id,
                               "bucket": bucket_name,
                               "pubsub_topic": pubsub_topic,
                               "email_secret": email_secret,
                               "password_secret": password_secret,
                               "page_size": page_size,
                               "force_latest": force_latest,
                           })

            # Add attributes to root span
            root_span.set_attribute("gcp.project_id", project_id or "")
            root_span.set_attribute("gcs.bucket", bucket_name or "")

            if not project_id or not bucket_name:
                log_structured("ERROR", "Missing required environment variables",
                               event="config_error")
                root_span.set_status(Status(StatusCode.ERROR, "Missing config"))
                return {"error": "Missing required environment variables"}, 500

            # Get credentials from Secret Manager
            with tracer.start_as_current_span("get_secrets") as span:
                email = get_secret(email_secret, project_id)
                password = get_secret(password_secret, project_id)
                span.set_attribute("secrets.count", 2)

            # Initialize clients
            otter = OtterClient(email, password)
            storage_client = storage.Client()
            bucket = storage_client.bucket(bucket_name)

            # Authenticate with Otter
            with tracer.start_as_current_span("otter_authenticate") as span:
                otter.authenticate()
                span.set_attribute("otter.user_id", otter.user_id or "")
                log_structured("INFO", "Otter authentication successful",
                               event="auth_success")

            # Get processed IDs
            with tracer.start_as_current_span("get_processed_ids") as span:
                processed_ids = get_processed_ids(bucket)
                span.set_attribute("processed_ids.count", len(processed_ids))

            # Load topic mapping from GCS (folder_name -> hierarchical topic)
            with tracer.start_as_current_span("load_topic_mapping") as span:
                topic_mapping = get_topic_mapping(bucket)
                span.set_attribute("topic_mapping.count", len(topic_mapping.get("mappings", {})))
                log_structured("INFO", f"Loaded topic mapping with {len(topic_mapping.get('mappings', {}))} entries",
                               event="topic_mapping_loaded",
                               mapping_count=len(topic_mapping.get("mappings", {})))

            # Get recent speeches
            with tracer.start_as_current_span("fetch_speeches") as span:
                speeches = otter.get_speeches(page_size=page_size)
                span.set_attribute("speeches.fetched", len(speeches))
                log_structured("INFO", f"Retrieved {len(speeches)} speeches from Otter",
                               event="speeches_fetched",
                               speech_count=len(speeches))

            new_count = 0
            synced_speeches = []
            errors = []

            # If force_latest is set, remove the latest speech ID from processed_ids
            # so it will be re-processed (useful for testing)
            forced_speech_id = None
            if force_latest and speeches:
                forced_speech_id = speeches[0].get("otid") or speeches[0].get("id")
                if forced_speech_id:
                    # Convert to string for consistent comparison and storage
                    forced_speech_id = str(forced_speech_id)
                    log_structured("INFO", f"force_latest: Re-processing speech {forced_speech_id}",
                                   event="force_latest_triggered",
                                   speech_id=forced_speech_id)
                    # Remove both string and original forms from processed_ids
                    processed_ids.discard(forced_speech_id)
                    processed_ids.discard(speeches[0].get("otid"))
                    processed_ids.discard(speeches[0].get("id"))

            for speech_meta in speeches:
                # Otter uses 'otid' for speech IDs - convert to string for consistency
                speech_id = speech_meta.get("otid") or speech_meta.get("id")
                if speech_id is not None:
                    speech_id = str(speech_id)

                if speech_id in processed_ids:
                    continue

                # If force_latest, only process the first (latest) speech
                if force_latest and forced_speech_id and speech_id != forced_speech_id:
                    continue

                # Create a span for each transcript sync
                with tracer.start_as_current_span(
                    "process_transcript",
                    attributes={"speech.id": speech_id or "unknown"}
                ) as span:
                    try:
                        # Get full speech with transcript
                        speech = otter.get_speech(speech_id)
                        span.set_attribute("speech.title", speech.get("title") or "Untitled")

                        # Get folder name directly from speech metadata (more reliable than folder iteration)
                        # The 'folder' field is a dict with 'folder_name' key, or None if not in a folder
                        folder_field = speech.get("folder") or speech_meta.get("folder")
                        if isinstance(folder_field, dict):
                            folder_name = folder_field.get("folder_name") or "General"
                        else:
                            folder_name = "General"

                        # Resolve folder name to hierarchical topic using mapping
                        topic = resolve_topic(folder_name, topic_mapping)
                        span.set_attribute("speech.folder", folder_name or "General")
                        span.set_attribute("speech.topic", topic or "General")

                        # Format transcript as JSON (using resolved topic)
                        transcript_data = otter.format_transcript_json(speech, topic)
                        span.set_attribute("transcript.segment_count", transcript_data.get("segment_count") or 0)

                        with tracer.start_as_current_span("upload_to_gcs"):
                            blob_path = upload_transcript(bucket, speech, transcript_data)

                        span.set_attribute("gcs.blob_path", blob_path)
                        log_structured("INFO", f"Uploaded transcript: {speech.get('title')}",
                                       event="transcript_uploaded",
                                       speech_id=speech_id,
                                       topic=topic,
                                       blob_path=blob_path)

                        # Publish event if topic configured
                        if pubsub_topic:
                            with tracer.start_as_current_span("publish_event"):
                                publish_transcript_event(
                                    project_id, pubsub_topic, speech, bucket_name, blob_path,
                                    topic=topic
                                )

                        # Mark as processed
                        processed_ids.add(speech_id)
                        new_count += 1

                        synced_speeches.append({
                            "id": speech_id,
                            "title": speech.get("title"),
                            "topic": topic,
                            "path": blob_path
                        })

                    except Exception as e:
                        import traceback
                        span.set_status(Status(StatusCode.ERROR, str(e)))
                        span.record_exception(e)
                        # Get speech title from metadata if available
                        speech_title = speech_meta.get("title", "Unknown")
                        log_structured("WARNING", f"Failed to process speech {speech_id}: {type(e).__name__}: {str(e)}",
                                       event="speech_error",
                                       speech_id=speech_id,
                                       speech_title=speech_title,
                                       error=str(e),
                                       error_type=type(e).__name__,
                                       traceback=traceback.format_exc())
                        errors.append({"id": speech_id, "title": speech_title, "error": str(e), "error_type": type(e).__name__})

            # Save updated processed IDs
            with tracer.start_as_current_span("save_processed_ids"):
                save_processed_ids(bucket, processed_ids)

            duration_ms = int((time.time() - start_time) * 1000)

            # Set final span attributes
            root_span.set_attribute("sync.new_transcripts", new_count)
            root_span.set_attribute("sync.total_processed", len(processed_ids))
            root_span.set_attribute("sync.errors", len(errors))
            root_span.set_attribute("sync.duration_ms", duration_ms)
            root_span.set_status(Status(StatusCode.OK))

            result = {
                "status": "success",
                "new_transcripts": new_count,
                "total_processed": len(processed_ids),
                "synced": synced_speeches,
                "errors": errors,
                "duration_ms": duration_ms
            }

            log_structured("INFO", f"========== OTTER SYNC COMPLETED (HTTP): {new_count} new transcripts in {duration_ms}ms ==========",
                           event="sync_completed",
                           new_transcripts=new_count,
                           total_processed=len(processed_ids),
                           error_count=len(errors),
                           duration_ms=duration_ms,
                           trigger="http")

            return result, 200

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            root_span.set_status(Status(StatusCode.ERROR, str(e)))
            root_span.record_exception(e)
            root_span.set_attribute("sync.duration_ms", duration_ms)
            log_structured("ERROR", f"========== OTTER SYNC FAILED (HTTP): {str(e)} ==========",
                           event="sync_failed",
                           error=str(e),
                           error_type=type(e).__name__,
                           duration_ms=duration_ms)
            return {"error": str(e)}, 500


@functions_framework.http
def health_check(request):
    """Simple health check endpoint."""
    return {"status": "healthy"}, 200


@functions_framework.cloud_event
def start_cycle(cloud_event):
    """
    Pub/Sub Cloud Event handler for "start-cycle" events.

    Triggered when a message is published to the configured Pub/Sub topic.
    This allows the sync to be initiated via Pub/Sub instead of HTTP.

    The Pub/Sub message can optionally include:
    - page_size: Number of speeches to fetch (default: 500, to get all speeches)
    - force_latest: If true, re-process the most recent conversation even if
                    already processed. Useful for testing (default: false)

    Deploy with:
        gcloud functions deploy otter-sync-pubsub \
            --gen2 \
            --trigger-topic=start-cycle \
            --entry-point=start_cycle

    Test with force_latest:
        gcloud pubsub topics publish start-cycle --message='{"force_latest": true}'
    """
    import base64

    # Initialize OpenTelemetry tracer
    tracer = get_tracer()

    # Start root span for the entire sync operation
    with tracer.start_as_current_span(
        "start_cycle_pubsub",
        kind=trace.SpanKind.SERVER,
    ) as root_span:
        start_time = time.time()

        # Extract message data if present
        # Gen2 Cloud Functions receive CloudEvents where data structure varies:
        # - Direct Pub/Sub: cloud_event.data["message"]["data"] (base64 encoded)
        # - Eventarc: cloud_event.data directly contains the message
        message_data = {}
        try:
            if cloud_event.data:
                raw_data = None

                # Try nested message structure first (Pub/Sub via Eventarc)
                if isinstance(cloud_event.data, dict) and "message" in cloud_event.data:
                    raw_data = cloud_event.data["message"].get("data", "")
                # Try direct data field (some Pub/Sub configurations)
                elif isinstance(cloud_event.data, dict) and "data" in cloud_event.data:
                    raw_data = cloud_event.data.get("data", "")
                # Data might be a string directly
                elif isinstance(cloud_event.data, str):
                    raw_data = cloud_event.data

                if raw_data:
                    # Try base64 decode first
                    try:
                        decoded = base64.b64decode(raw_data).decode("utf-8")
                        message_data = json.loads(decoded) if decoded else {}
                    except Exception:
                        # Maybe it's already JSON string, not base64
                        if isinstance(raw_data, str) and raw_data.startswith("{"):
                            message_data = json.loads(raw_data)

                log_structured("INFO", f"Parsed message data from cloud_event",
                              event="pubsub_message_parsed",
                              raw_data_type=type(cloud_event.data).__name__,
                              message_data=message_data)
        except Exception as e:
            log_structured("WARNING", f"Failed to parse Pub/Sub message data: {e}",
                          event="pubsub_parse_warning",
                          error=str(e),
                          cloud_event_data=str(cloud_event.data)[:500] if cloud_event.data else None)

        # Log event attributes
        event_id = cloud_event.get("id", "unknown")
        event_source = cloud_event.get("source", "unknown")
        root_span.set_attribute("cloudevent.id", event_id)
        root_span.set_attribute("cloudevent.source", event_source)

        try:
            # Get configuration
            project_id = os.environ.get("GCP_PROJECT")
            bucket_name = os.environ.get("GCS_BUCKET")
            email_secret = os.environ.get("OTTER_EMAIL_SECRET", "otter-email")
            password_secret = os.environ.get("OTTER_PASSWORD_SECRET", "otter-password")
            pubsub_topic = os.environ.get("PUBSUB_TOPIC")

            # Allow page_size and force_latest override from message
            page_size = message_data.get("page_size", 500)
            force_latest = message_data.get("force_latest", False)

            log_structured("INFO", "========== OTTER SYNC STARTED (PUB/SUB) ==========",
                          event="sync_started",
                          trigger="pubsub",
                          event_id=event_id,
                          event_source=event_source,
                          config={
                              "project_id": project_id,
                              "bucket": bucket_name,
                              "pubsub_topic": pubsub_topic,
                              "email_secret": email_secret,
                              "password_secret": password_secret,
                              "page_size": page_size,
                              "force_latest": force_latest,
                          },
                          message_data=message_data)

            # Add attributes to root span
            root_span.set_attribute("gcp.project_id", project_id or "")
            root_span.set_attribute("gcs.bucket", bucket_name or "")
            root_span.set_attribute("sync.page_size", page_size)
            root_span.set_attribute("sync.force_latest", force_latest)

            if not project_id or not bucket_name:
                log_structured("ERROR", "Missing required environment variables",
                               event="config_error")
                root_span.set_status(Status(StatusCode.ERROR, "Missing config"))
                raise ValueError("Missing required environment variables: GCP_PROJECT and GCS_BUCKET")

            # Get credentials from Secret Manager
            with tracer.start_as_current_span("get_secrets") as span:
                email = get_secret(email_secret, project_id)
                password = get_secret(password_secret, project_id)
                span.set_attribute("secrets.count", 2)

            # Initialize clients
            otter = OtterClient(email, password)
            storage_client = storage.Client()
            bucket = storage_client.bucket(bucket_name)

            # Authenticate with Otter
            with tracer.start_as_current_span("otter_authenticate") as span:
                otter.authenticate()
                span.set_attribute("otter.user_id", otter.user_id or "")
                log_structured("INFO", "Otter authentication successful",
                               event="auth_success")

            # Get processed IDs
            with tracer.start_as_current_span("get_processed_ids") as span:
                processed_ids = get_processed_ids(bucket)
                span.set_attribute("processed_ids.count", len(processed_ids))

            # Load topic mapping from GCS (folder_name -> hierarchical topic)
            with tracer.start_as_current_span("load_topic_mapping") as span:
                topic_mapping = get_topic_mapping(bucket)
                span.set_attribute("topic_mapping.count", len(topic_mapping.get("mappings", {})))
                log_structured("INFO", f"Loaded topic mapping with {len(topic_mapping.get('mappings', {}))} entries",
                               event="topic_mapping_loaded",
                               mapping_count=len(topic_mapping.get("mappings", {})))

            # Get recent speeches
            with tracer.start_as_current_span("fetch_speeches") as span:
                speeches = otter.get_speeches(page_size=page_size)
                span.set_attribute("speeches.fetched", len(speeches))
                log_structured("INFO", f"Retrieved {len(speeches)} speeches from Otter",
                               event="speeches_fetched",
                               speech_count=len(speeches))

            new_count = 0
            synced_speeches = []
            errors = []

            # If force_latest is set, remove the latest speech ID from processed_ids
            # so it will be re-processed (useful for testing)
            forced_speech_id = None
            if force_latest and speeches:
                forced_speech_id = speeches[0].get("otid") or speeches[0].get("id")
                if forced_speech_id:
                    # Convert to string for consistent comparison and storage
                    forced_speech_id = str(forced_speech_id)
                    log_structured("INFO", f"force_latest: Re-processing speech {forced_speech_id}",
                                   event="force_latest_triggered",
                                   speech_id=forced_speech_id)
                    # Remove both string and original forms from processed_ids
                    processed_ids.discard(forced_speech_id)
                    processed_ids.discard(speeches[0].get("otid"))
                    processed_ids.discard(speeches[0].get("id"))

            for speech_meta in speeches:
                # Otter uses 'otid' for speech IDs - convert to string for consistency
                speech_id = speech_meta.get("otid") or speech_meta.get("id")
                if speech_id is not None:
                    speech_id = str(speech_id)

                if speech_id in processed_ids:
                    continue

                # If force_latest, only process the first (latest) speech
                if force_latest and forced_speech_id and speech_id != forced_speech_id:
                    continue

                # Create a span for each transcript sync
                with tracer.start_as_current_span(
                    "process_transcript",
                    attributes={"speech.id": speech_id or "unknown"}
                ) as span:
                    try:
                        # Get full speech with transcript
                        speech = otter.get_speech(speech_id)
                        span.set_attribute("speech.title", speech.get("title") or "Untitled")

                        # Get folder name directly from speech metadata
                        folder_field = speech.get("folder") or speech_meta.get("folder")
                        if isinstance(folder_field, dict):
                            folder_name = folder_field.get("folder_name") or "General"
                        else:
                            folder_name = "General"

                        # Resolve folder name to hierarchical topic using mapping
                        topic = resolve_topic(folder_name, topic_mapping)
                        span.set_attribute("speech.folder", folder_name or "General")
                        span.set_attribute("speech.topic", topic or "General")

                        # Format transcript as JSON (using resolved topic)
                        transcript_data = otter.format_transcript_json(speech, topic)
                        span.set_attribute("transcript.segment_count", transcript_data.get("segment_count") or 0)

                        with tracer.start_as_current_span("upload_to_gcs"):
                            blob_path = upload_transcript(bucket, speech, transcript_data)

                        span.set_attribute("gcs.blob_path", blob_path)
                        log_structured("INFO", f"Uploaded transcript: {speech.get('title')}",
                                       event="transcript_uploaded",
                                       speech_id=speech_id,
                                       topic=topic,
                                       blob_path=blob_path)

                        # Publish event if topic configured
                        if pubsub_topic:
                            with tracer.start_as_current_span("publish_event"):
                                publish_transcript_event(
                                    project_id, pubsub_topic, speech, bucket_name, blob_path,
                                    topic=topic
                                )

                        # Mark as processed
                        processed_ids.add(speech_id)
                        new_count += 1

                        synced_speeches.append({
                            "id": speech_id,
                            "title": speech.get("title"),
                            "topic": topic,
                            "path": blob_path
                        })

                    except Exception as e:
                        import traceback
                        span.set_status(Status(StatusCode.ERROR, str(e)))
                        span.record_exception(e)
                        # Get speech title from metadata if available
                        speech_title = speech_meta.get("title", "Unknown")
                        log_structured("WARNING", f"Failed to process speech {speech_id}: {type(e).__name__}: {str(e)}",
                                       event="speech_error",
                                       speech_id=speech_id,
                                       speech_title=speech_title,
                                       error=str(e),
                                       error_type=type(e).__name__,
                                       traceback=traceback.format_exc())
                        errors.append({"id": speech_id, "title": speech_title, "error": str(e), "error_type": type(e).__name__})

            # Save updated processed IDs
            with tracer.start_as_current_span("save_processed_ids"):
                save_processed_ids(bucket, processed_ids)

            duration_ms = int((time.time() - start_time) * 1000)

            # Set final span attributes
            root_span.set_attribute("sync.new_transcripts", new_count)
            root_span.set_attribute("sync.total_processed", len(processed_ids))
            root_span.set_attribute("sync.errors", len(errors))
            root_span.set_attribute("sync.duration_ms", duration_ms)
            root_span.set_status(Status(StatusCode.OK))

            log_structured("INFO", f"========== OTTER SYNC COMPLETED (PUB/SUB): {new_count} new transcripts in {duration_ms}ms ==========",
                           event="sync_completed",
                           new_transcripts=new_count,
                           total_processed=len(processed_ids),
                           error_count=len(errors),
                           duration_ms=duration_ms,
                           trigger="pubsub")

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            root_span.set_status(Status(StatusCode.ERROR, str(e)))
            root_span.record_exception(e)
            root_span.set_attribute("sync.duration_ms", duration_ms)
            log_structured("ERROR", f"========== OTTER SYNC FAILED (PUB/SUB): {str(e)} ==========",
                           event="sync_failed",
                           error=str(e),
                           error_type=type(e).__name__,
                           duration_ms=duration_ms,
                           trigger="pubsub")
            raise
