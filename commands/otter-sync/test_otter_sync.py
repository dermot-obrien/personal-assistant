"""
Unit tests for Otter sync Cloud Function.

These tests mock GCS and Otter API, writing output to a local folder
for inspection and validation.

Usage:
    pytest test_otter_sync.py -v
    pytest test_otter_sync.py -v -k "test_format"  # Run specific tests
"""

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Import the module under test
from main import (
    OtterClient,
    upload_transcript,
    resolve_topic,
    get_topic_mapping,
    get_processed_ids,
    save_processed_ids,
)


# --- Test Output Directory ---

TEST_OUTPUT_DIR = Path(__file__).parent / "test_output"


@pytest.fixture(scope="session", autouse=True)
def setup_test_output_dir():
    """Create and clean test output directory."""
    if TEST_OUTPUT_DIR.exists():
        shutil.rmtree(TEST_OUTPUT_DIR)
    TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    yield
    # Optionally clean up after tests (comment out to keep files for inspection)
    # shutil.rmtree(TEST_OUTPUT_DIR)


def write_test_output(filename: str, data: Any, subdir: str = "") -> Path:
    """Write test output to local folder for inspection."""
    output_dir = TEST_OUTPUT_DIR / subdir if subdir else TEST_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    filepath = output_dir / filename

    if isinstance(data, (dict, list)):
        filepath = filepath.with_suffix(".json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    else:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(str(data))

    return filepath


# --- Mock Data Fixtures ---

@pytest.fixture
def sample_speech_basic():
    """Basic speech data with minimal fields."""
    return {
        "otid": "speech123",
        "id": "speech123",
        "title": "Team Meeting",
        "created_at": 1702684800,  # 2023-12-16 00:00:00 UTC
        "start_time": 1702684800,
        "end_time": 1702688400,
        "duration": 3600,
        "speakers": [
            {"id": 1, "speaker_name": "Alice"},
            {"id": 2, "speaker_name": "Bob"},
        ],
        "transcripts": [
            {
                "speaker_id": 1,
                "transcript": "Hello everyone, let's get started.",
                "start_offset": 0,
                "end_offset": 3000,
            },
            {
                "speaker_id": 2,
                "transcript": "Thanks Alice. I have some updates.",
                "start_offset": 3000,
                "end_offset": 6000,
            },
        ],
        "summary": "A team meeting discussing project updates.",
        "folder": {"id": "folder1", "folder_name": "Work"},
    }


@pytest.fixture
def sample_speech_with_control_chars():
    """Speech data with control characters that need sanitization."""
    return {
        "otid": "speech456",
        "title": "Meeting\x00with\x08special\x1fchars",
        "created_at": 1702684800,
        "speakers": [{"id": 1, "speaker_name": "Speaker"}],
        "transcripts": [
            {
                "speaker_id": 1,
                "transcript": "Text with\x00null and\x08backspace\x1fchars",
                "start_offset": 0,
                "end_offset": 3000,
            },
        ],
        "summary": "Summary\x00with\x1fcontrol\x08characters",
    }


@pytest.fixture
def sample_speech_with_string_outline():
    """Speech data where speech_outline is a Python-style string representation."""
    return {
        "otid": "speech789",
        "title": "Meeting with Outline",
        "created_at": 1702684800,
        "speakers": [],
        "transcripts": [],
        "speech_outline": "[{'title': 'Introduction', 'start_time': 0}, {'title': 'Discussion', 'start_time': 60}]",
    }


@pytest.fixture
def sample_speech_with_none_fields():
    """Speech data with None values that could cause iteration errors."""
    return {
        "otid": "speech_none",
        "title": "Meeting with None fields",
        "created_at": 1702684800,
        "speakers": None,  # This should not cause iteration error
        "transcripts": None,  # This should not cause iteration error
        "summary": None,
        "folder": None,
    }


@pytest.fixture
def sample_speech_full():
    """Full speech data with all common fields."""
    return {
        "otid": "full_speech_id",
        "id": "full_speech_id",
        "speech_id": "full_speech_id",
        "meeting_otid": "meeting123",
        "title": "Comprehensive Team Sync - Q4 Planning",
        "created_at": 1702684800,
        "start_time": 1702684800,
        "end_time": 1702692000,
        "duration": 7200,
        "timezone": "America/New_York",
        "language": "en",
        "speakers": [
            {"id": 1, "speaker_name": "Alice Johnson"},
            {"id": 2, "speaker_name": "Bob Smith"},
            {"id": 3, "speaker_name": "Carol Davis"},
        ],
        "transcripts": [
            {
                "speaker_id": 1,
                "transcript": "Good morning everyone. Welcome to our Q4 planning session.",
                "start_offset": 0,
                "end_offset": 5000,
            },
            {
                "speaker_id": 2,
                "transcript": "Thanks Alice. I've prepared the quarterly reports.",
                "start_offset": 5000,
                "end_offset": 10000,
            },
            {
                "speaker_id": 3,
                "transcript": "Great work Bob. Let me share the customer feedback.",
                "start_offset": 10000,
                "end_offset": 15000,
            },
            {
                "speaker_id": 1,
                "transcript": "Excellent. Let's discuss the roadmap for next quarter.",
                "start_offset": 15000,
                "end_offset": 20000,
            },
        ],
        "summary": "Q4 planning meeting covering quarterly reports and customer feedback.",
        "short_abstract_summary": "Team sync for Q4 planning",
        "speech_outline": [
            {"title": "Welcome", "start_time": 0},
            {"title": "Reports", "start_time": 5},
            {"title": "Feedback", "start_time": 10},
            {"title": "Roadmap", "start_time": 15},
        ],
        "folder": {"id": "folder_work", "folder_name": "Work Meetings"},
        "process_finished": True,
        "process_status": "completed",
        "is_low_confidence": False,
        "create_method": "live",
        "audio_enabled": True,
        "action_item_count": 3,
        "owner": {"id": "user123", "name": "Alice Johnson"},
    }


@pytest.fixture
def topic_mapping():
    """Sample topic mapping configuration."""
    return {
        "default": "General",
        "mappings": {
            "Work Meetings": "Work/Meetings",
            "Personal": "Personal/Notes",
            "Daily Journal": "Personal/Journal",
        }
    }


# --- OtterClient Tests ---

class TestOtterClientSanitization:
    """Tests for text sanitization methods."""

    def test_sanitize_text_removes_null_bytes(self):
        """Test that null bytes are removed from text."""
        client = OtterClient("test@test.com", "password")
        result = client._sanitize_text("Hello\x00World")
        assert result == "HelloWorld"
        assert "\x00" not in result

    def test_sanitize_text_removes_control_chars(self):
        """Test that control characters (except newline/tab/cr) are removed."""
        client = OtterClient("test@test.com", "password")
        result = client._sanitize_text("Text\x08with\x1fcontrol\x7fchars")
        assert "\x08" not in result
        assert "\x1f" not in result
        assert "\x7f" not in result

    def test_sanitize_text_preserves_newlines_tabs(self):
        """Test that newlines and tabs are preserved."""
        client = OtterClient("test@test.com", "password")
        result = client._sanitize_text("Line1\nLine2\tTabbed")
        assert "\n" in result
        assert "\t" in result

    def test_sanitize_text_handles_empty(self):
        """Test handling of empty/None input."""
        client = OtterClient("test@test.com", "password")
        assert client._sanitize_text("") == ""
        assert client._sanitize_text(None) == ""

    def test_sanitize_text_handles_unicode(self):
        """Test that unicode characters are preserved."""
        client = OtterClient("test@test.com", "password")
        result = client._sanitize_text("Hello 世界 🌍 Émoji")
        assert "世界" in result
        assert "🌍" in result
        assert "É" in result


class TestOtterClientOutlineParsing:
    """Tests for speech_outline parsing."""

    def test_parse_speech_outline_list(self):
        """Test parsing when outline is already a list."""
        client = OtterClient("test@test.com", "password")
        outline = [{"title": "Intro"}, {"title": "Main"}]
        result = client._parse_speech_outline(outline)
        assert result == outline

    def test_parse_speech_outline_json_string(self):
        """Test parsing when outline is a JSON string."""
        client = OtterClient("test@test.com", "password")
        outline = '[{"title": "Intro"}, {"title": "Main"}]'
        result = client._parse_speech_outline(outline)
        assert result == [{"title": "Intro"}, {"title": "Main"}]

    def test_parse_speech_outline_python_string(self):
        """Test parsing when outline is a Python-style string (single quotes)."""
        client = OtterClient("test@test.com", "password")
        outline = "[{'title': 'Intro'}, {'title': 'Main'}]"
        result = client._parse_speech_outline(outline)
        assert result == [{"title": "Intro"}, {"title": "Main"}]

    def test_parse_speech_outline_none(self):
        """Test handling of None outline."""
        client = OtterClient("test@test.com", "password")
        assert client._parse_speech_outline(None) is None

    def test_parse_speech_outline_invalid_string(self):
        """Test handling of invalid string."""
        client = OtterClient("test@test.com", "password")
        assert client._parse_speech_outline("not a valid list") is None


class TestOtterClientFormatTranscript:
    """Tests for transcript formatting."""

    def test_format_basic_transcript(self, sample_speech_basic):
        """Test formatting a basic transcript."""
        client = OtterClient("test@test.com", "password")
        result = client.format_transcript_json(sample_speech_basic)

        # Write output for inspection
        write_test_output("basic_transcript", result, "transcripts")

        # Validate structure
        assert result["otter_id"] == "speech123"
        assert result["title"] == "Team Meeting"
        assert result["segment_count"] == 2
        assert len(result["segments"]) == 2
        # speaker_map stores both id and str(id) for each speaker, so count is 4 (2 speakers * 2 keys each)
        assert result["speaker_count"] == 4
        # But unique speaker names should be 2
        assert len(set(result["speaker_names"])) == 2

        # Validate speaker resolution
        assert result["segments"][0]["speaker"] == "Alice"
        assert result["segments"][1]["speaker"] == "Bob"

        # Validate timestamps
        assert result["created_at"] is not None
        assert result["created_at_unix"] == 1702684800

    def test_format_transcript_with_control_chars(self, sample_speech_with_control_chars):
        """Test that control characters are sanitized."""
        client = OtterClient("test@test.com", "password")
        result = client.format_transcript_json(sample_speech_with_control_chars)

        write_test_output("sanitized_transcript", result, "transcripts")

        # Validate control chars removed
        assert "\x00" not in result["title"]
        assert "\x08" not in result["title"]
        assert "\x1f" not in result["title"]
        assert "\x00" not in result["summary"]

        # Validate content preserved
        assert "special" in result["title"]
        assert "chars" in result["title"]

    def test_format_transcript_with_string_outline(self, sample_speech_with_string_outline):
        """Test that Python-style string outlines are parsed."""
        client = OtterClient("test@test.com", "password")
        result = client.format_transcript_json(sample_speech_with_string_outline)

        write_test_output("string_outline_transcript", result, "transcripts")

        # Validate outline was parsed
        assert result["speech_outline"] is not None
        assert isinstance(result["speech_outline"], list)
        assert len(result["speech_outline"]) == 2
        assert result["speech_outline"][0]["title"] == "Introduction"

    def test_format_transcript_with_none_fields(self, sample_speech_with_none_fields):
        """Test that None fields don't cause iteration errors."""
        client = OtterClient("test@test.com", "password")

        # This should not raise TypeError: 'NoneType' object is not iterable
        result = client.format_transcript_json(sample_speech_with_none_fields)

        write_test_output("none_fields_transcript", result, "transcripts")

        # Validate graceful handling
        assert result["otter_id"] == "speech_none"
        assert result["segments"] == []
        assert result["speakers"] == []
        assert result["speaker_count"] == 0

    def test_format_transcript_with_folder_name(self, sample_speech_basic):
        """Test that folder_name parameter is used as topic."""
        client = OtterClient("test@test.com", "password")
        result = client.format_transcript_json(sample_speech_basic, folder_name="Custom/Topic")

        assert result["topic"] == "Custom/Topic"

    def test_format_full_transcript(self, sample_speech_full):
        """Test formatting a full transcript with all fields."""
        client = OtterClient("test@test.com", "password")
        result = client.format_transcript_json(sample_speech_full)

        write_test_output("full_transcript", result, "transcripts")

        # Validate all major fields
        assert result["otter_id"] == "full_speech_id"
        assert result["meeting_otid"] == "meeting123"
        assert result["title"] == "Comprehensive Team Sync - Q4 Planning"
        assert result["segment_count"] == 4
        assert result["duration"] == 7200
        assert result["language"] == "en"
        assert result["process_finished"] is True
        assert result["action_item_count"] == 3

        # Validate speakers
        assert "Alice Johnson" in result["speaker_names"]
        assert "Bob Smith" in result["speaker_names"]
        assert "Carol Davis" in result["speaker_names"]

        # Validate outline is list (not string)
        assert isinstance(result["speech_outline"], list)

        # Validate full_text contains all segments
        assert "Q4 planning session" in result["full_text"]
        assert "quarterly reports" in result["full_text"]

    def test_format_transcript_raises_on_none_speech(self):
        """Test that None speech data raises ValueError."""
        client = OtterClient("test@test.com", "password")

        with pytest.raises(ValueError, match="Speech data is None or empty"):
            client.format_transcript_json(None)

    def test_format_transcript_raises_on_non_dict(self):
        """Test that non-dict speech data raises ValueError."""
        client = OtterClient("test@test.com", "password")

        with pytest.raises(ValueError, match="Speech data is not a dict"):
            client.format_transcript_json("not a dict")


# --- Topic Mapping Tests ---

class TestTopicMapping:
    """Tests for topic resolution."""

    def test_resolve_mapped_topic(self, topic_mapping):
        """Test resolving a mapped folder name."""
        result = resolve_topic("Work Meetings", topic_mapping)
        assert result == "Work/Meetings"

    def test_resolve_unmapped_topic(self, topic_mapping):
        """Test that unmapped folders keep their name."""
        result = resolve_topic("Random Folder", topic_mapping)
        assert result == "Random Folder"

    def test_resolve_general_uses_default(self, topic_mapping):
        """Test that 'General' uses the default topic."""
        result = resolve_topic("General", topic_mapping)
        assert result == "General"  # Default in fixture

    def test_resolve_with_empty_mapping(self):
        """Test resolution with empty mapping."""
        empty_mapping = {"default": "Default", "mappings": {}}
        result = resolve_topic("Some Folder", empty_mapping)
        assert result == "Some Folder"


# --- JSON Validation Tests ---

class TestJsonValidation:
    """Tests to validate JSON output structure and content."""

    def test_json_is_valid(self, sample_speech_full):
        """Test that output is valid JSON."""
        client = OtterClient("test@test.com", "password")
        result = client.format_transcript_json(sample_speech_full)

        # Convert to JSON string and back - should not raise
        json_str = json.dumps(result, ensure_ascii=False)
        parsed = json.loads(json_str)

        assert parsed["otter_id"] == result["otter_id"]

    def test_json_no_control_chars(self, sample_speech_with_control_chars):
        """Test that JSON output has no control characters."""
        client = OtterClient("test@test.com", "password")
        result = client.format_transcript_json(sample_speech_with_control_chars)

        json_str = json.dumps(result, ensure_ascii=False)

        # Check for common control characters
        for char_code in range(0x00, 0x20):
            if char_code not in (0x09, 0x0A, 0x0D):  # Allow tab, newline, CR
                assert chr(char_code) not in json_str, f"Found control char 0x{char_code:02x}"

    def test_json_required_fields_present(self, sample_speech_basic):
        """Test that all required fields are present in output."""
        client = OtterClient("test@test.com", "password")
        result = client.format_transcript_json(sample_speech_basic)

        required_fields = [
            "otter_id",
            "title",
            "topic",
            "created_at",
            "segments",
            "segment_count",
            "speakers",
            "speaker_count",
            "full_text",
        ]

        for field in required_fields:
            assert field in result, f"Missing required field: {field}"


# --- Mock GCS Tests ---

class MockBlob:
    """Mock GCS blob for testing."""

    def __init__(self, name: str, bucket: "MockBucket"):
        self.name = name
        self.bucket = bucket
        self.metadata = {}
        self._content = None

    def upload_from_string(self, content: str, content_type: str = None):
        self._content = content
        # Write to local test folder
        filepath = TEST_OUTPUT_DIR / "gcs" / self.name
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

    def download_as_text(self) -> str:
        return self._content or ""

    def exists(self) -> bool:
        return self._content is not None

    def patch(self):
        pass


class MockBucket:
    """Mock GCS bucket for testing."""

    def __init__(self, name: str):
        self.name = name
        self._blobs: dict[str, MockBlob] = {}

    def blob(self, name: str) -> MockBlob:
        if name not in self._blobs:
            self._blobs[name] = MockBlob(name, self)
        return self._blobs[name]


class TestLocalGCSOutput:
    """Tests that write output to local folder (mocking GCS)."""

    def test_upload_transcript_creates_file(self, sample_speech_full):
        """Test that upload_transcript creates a local JSON file."""
        client = OtterClient("test@test.com", "password")
        transcript_data = client.format_transcript_json(sample_speech_full, "Work/Meetings")

        bucket = MockBucket("test-bucket")

        blob_path = upload_transcript(bucket, sample_speech_full, transcript_data)

        # Verify file was created
        local_path = TEST_OUTPUT_DIR / "gcs" / blob_path
        assert local_path.exists(), f"File not created: {local_path}"

        # Verify content is valid JSON
        with open(local_path, "r", encoding="utf-8") as f:
            saved_data = json.load(f)

        assert saved_data["otter_id"] == "full_speech_id"
        assert saved_data["topic"] == "Work/Meetings"
        assert "synced_at" in saved_data

    def test_upload_multiple_transcripts(self, sample_speech_basic, sample_speech_full):
        """Test uploading multiple transcripts."""
        client = OtterClient("test@test.com", "password")
        bucket = MockBucket("test-bucket")

        speeches = [
            (sample_speech_basic, "Work"),
            (sample_speech_full, "Personal"),
        ]

        created_files = []
        for speech, topic in speeches:
            transcript_data = client.format_transcript_json(speech, topic)
            blob_path = upload_transcript(bucket, speech, transcript_data)
            created_files.append(TEST_OUTPUT_DIR / "gcs" / blob_path)

        # Verify all files created
        for filepath in created_files:
            assert filepath.exists(), f"File not created: {filepath}"


class TestProcessedIds:
    """Tests for processed IDs tracking."""

    def test_save_and_get_processed_ids(self):
        """Test saving and retrieving processed IDs."""
        bucket = MockBucket("test-bucket")

        # Initially empty
        ids = get_processed_ids(bucket)
        assert ids == set()

        # Save some IDs
        test_ids = {"id1", "id2", "id3"}
        save_processed_ids(bucket, test_ids)

        # Retrieve and verify
        retrieved = get_processed_ids(bucket)
        assert retrieved == test_ids


# --- Integration Test ---

class TestIntegration:
    """Integration tests that simulate full sync workflow."""

    def test_full_sync_workflow(self, sample_speech_full, topic_mapping):
        """Test complete sync workflow with local output."""
        # Setup
        client = OtterClient("test@test.com", "password")
        bucket = MockBucket("integration-test-bucket")

        # Simulate getting speeches from Otter
        speeches = [sample_speech_full]
        processed_ids = set()

        results = []

        for speech in speeches:
            speech_id = str(speech.get("otid") or speech.get("id"))

            if speech_id in processed_ids:
                continue

            # Get folder from speech
            folder_field = speech.get("folder")
            if isinstance(folder_field, dict):
                folder_name = folder_field.get("folder_name") or "General"
            else:
                folder_name = "General"

            # Resolve topic
            topic = resolve_topic(folder_name, topic_mapping)

            # Format transcript
            transcript_data = client.format_transcript_json(speech, topic)

            # Upload (to local folder via mock)
            blob_path = upload_transcript(bucket, speech, transcript_data)

            # Track processed
            processed_ids.add(speech_id)

            results.append({
                "id": speech_id,
                "title": speech.get("title"),
                "topic": topic,
                "path": blob_path,
            })

        # Save processed IDs
        save_processed_ids(bucket, processed_ids)

        # Write summary for inspection
        write_test_output("integration_results", {
            "processed_count": len(results),
            "results": results,
        }, "integration")

        # Verify
        assert len(results) == 1
        assert results[0]["topic"] == "Work/Meetings"

        # Verify file exists
        local_path = TEST_OUTPUT_DIR / "gcs" / results[0]["path"]
        assert local_path.exists()


# --- Edge Case Tests ---

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_transcripts_list(self):
        """Test speech with empty transcripts list."""
        client = OtterClient("test@test.com", "password")
        speech = {
            "otid": "empty_transcripts",
            "title": "Empty Meeting",
            "created_at": 1702684800,
            "speakers": [],
            "transcripts": [],
        }

        result = client.format_transcript_json(speech)

        assert result["segments"] == []
        assert result["segment_count"] == 0
        assert result["full_text"] == ""

    def test_missing_speaker_info(self):
        """Test transcript segment with missing speaker info."""
        client = OtterClient("test@test.com", "password")
        speech = {
            "otid": "missing_speaker",
            "title": "No Speaker",
            "created_at": 1702684800,
            "speakers": [],  # No speaker mapping
            "transcripts": [
                {
                    "speaker_id": 999,  # Unknown speaker
                    "transcript": "Hello world",
                    "start_offset": 0,
                    "end_offset": 1000,
                },
            ],
        }

        result = client.format_transcript_json(speech)

        write_test_output("missing_speaker_transcript", result, "edge_cases")

        # Should use fallback speaker name
        assert result["segments"][0]["speaker"] == "Speaker"

    def test_very_long_title(self):
        """Test speech with very long title (should be truncated in filename)."""
        client = OtterClient("test@test.com", "password")
        long_title = "A" * 200  # Very long title
        speech = {
            "otid": "long_title",
            "title": long_title,
            "created_at": 1702684800,
            "speakers": [],
            "transcripts": [],
        }

        result = client.format_transcript_json(speech)
        bucket = MockBucket("test-bucket")
        blob_path = upload_transcript(bucket, speech, result)

        # Title in JSON should be full
        assert result["title"] == long_title

        # Filename should be reasonable length
        assert len(blob_path) < 200

    def test_special_chars_in_title(self):
        """Test speech with special characters in title."""
        client = OtterClient("test@test.com", "password")
        speech = {
            "otid": "special_chars",
            "title": "Meeting: Q&A / Review <2024>",
            "created_at": 1702684800,
            "speakers": [],
            "transcripts": [],
        }

        result = client.format_transcript_json(speech)
        bucket = MockBucket("test-bucket")
        blob_path = upload_transcript(bucket, speech, result)

        # JSON title should preserve special chars
        assert result["title"] == "Meeting: Q&A / Review <2024>"

        # Filename should have special chars replaced
        assert "<" not in blob_path
        assert ">" not in blob_path
        assert "/" not in blob_path.split("transcripts/")[1].rsplit("/", 1)[0] if "/" in blob_path else True


# --- Live Otter API Tests (disabled by default) ---


@pytest.fixture
def otter_credentials():
    """Get Otter credentials from environment or .env file."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    email = os.environ.get("OTTER_EMAIL")
    password = os.environ.get("OTTER_PASSWORD")

    if not email or not password:
        pytest.skip("OTTER_EMAIL and OTTER_PASSWORD environment variables required")

    return {"email": email, "password": password}


@pytest.mark.live_otter
class TestLiveOtterAPI:
    """
    Live tests that connect to real Otter API and download transcripts.

    DISABLED BY DEFAULT. To run these tests:
        pytest test_otter_sync.py -v -m live_otter

    Requires:
        - OTTER_EMAIL and OTTER_PASSWORD in environment or .env file
        - python-dotenv package (optional, for .env file support)

    Output:
        - All transcripts saved to test_output/live_otter/transcripts/
        - Summary report saved to test_output/live_otter/sync_report.json
    """

    def test_fetch_all_transcripts(self, otter_credentials):
        """
        Fetch ALL transcripts from Otter and save locally.

        This test:
        1. Authenticates with Otter API
        2. Retrieves all available speeches (up to 500)
        3. Downloads full transcript for each
        4. Formats and saves as JSON to local folder
        5. Generates a summary report
        """
        output_dir = TEST_OUTPUT_DIR / "live_otter" / "transcripts"
        output_dir.mkdir(parents=True, exist_ok=True)

        client = OtterClient(otter_credentials["email"], otter_credentials["password"])

        # Authenticate
        print("\n[1/5] Authenticating with Otter...")
        client.authenticate()
        print(f"      Authenticated as user: {client.user_id}")

        # Get folder mapping for topic resolution
        print("[2/5] Building folder mapping...")
        folder_map = client.get_folder_speech_mapping()
        print(f"      Found {len(folder_map)} speeches in folders")

        # Get all speeches (large page size to get everything)
        print("[3/5] Fetching speech list...")
        speeches = client.get_speeches(page_size=500)
        print(f"      Found {len(speeches)} total speeches")

        # Process each speech
        print("[4/5] Downloading and formatting transcripts...")
        results = []
        errors = []

        for i, speech_meta in enumerate(speeches, 1):
            speech_id = speech_meta.get("otid") or speech_meta.get("id")
            title = speech_meta.get("title", "Untitled")

            try:
                # Get full speech data
                speech = client.get_speech(speech_id)

                # Determine folder/topic
                folder_field = speech.get("folder") or speech_meta.get("folder")
                if isinstance(folder_field, dict):
                    folder_name = folder_field.get("folder_name") or "General"
                else:
                    folder_name = folder_map.get(str(speech_id), "General")

                # Format transcript
                transcript_data = client.format_transcript_json(speech, folder_name)

                # Generate filename
                created = speech.get("created_at", 0)
                if created:
                    from datetime import datetime
                    from zoneinfo import ZoneInfo
                    utc_dt = datetime.fromtimestamp(created, tz=timezone.utc)
                    local_dt = utc_dt.astimezone(ZoneInfo("Pacific/Auckland"))
                    datetime_str = local_dt.strftime("%Y-%m-%d_%H-%M")
                else:
                    datetime_str = "unknown_date"

                safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
                safe_title = safe_title[:50].strip()
                filename = f"{datetime_str}_{safe_title}_{speech_id}.json"

                # Save to local folder
                filepath = output_dir / filename
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(transcript_data, f, indent=2, ensure_ascii=False)

                results.append({
                    "id": speech_id,
                    "title": title,
                    "folder": folder_name,
                    "segment_count": transcript_data.get("segment_count", 0),
                    "speaker_count": len(set(transcript_data.get("speaker_names", []))),
                    "filename": filename,
                })

                print(f"      [{i}/{len(speeches)}] {title[:40]}... OK")

            except Exception as e:
                errors.append({
                    "id": speech_id,
                    "title": title,
                    "error": str(e),
                    "error_type": type(e).__name__,
                })
                print(f"      [{i}/{len(speeches)}] {title[:40]}... ERROR: {e}")

        # Generate summary report
        print("[5/5] Generating summary report...")
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": client.user_id,
            "total_speeches": len(speeches),
            "successful": len(results),
            "failed": len(errors),
            "output_directory": str(output_dir),
            "transcripts": results,
            "errors": errors,
        }

        report_path = TEST_OUTPUT_DIR / "live_otter" / "sync_report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"\n      Summary:")
        print(f"      - Total speeches: {len(speeches)}")
        print(f"      - Successfully saved: {len(results)}")
        print(f"      - Errors: {len(errors)}")
        print(f"      - Output: {output_dir}")
        print(f"      - Report: {report_path}")

        # Assertions
        assert len(results) > 0, "Should have downloaded at least one transcript"
        assert len(results) + len(errors) == len(speeches), "All speeches should be processed"

    def test_fetch_latest_transcript(self, otter_credentials):
        """
        Fetch only the latest transcript (quick test).

        Useful for verifying API connectivity and format without
        downloading all transcripts.
        """
        output_dir = TEST_OUTPUT_DIR / "live_otter" / "latest"
        output_dir.mkdir(parents=True, exist_ok=True)

        client = OtterClient(otter_credentials["email"], otter_credentials["password"])

        # Authenticate and get latest
        client.authenticate()
        speeches = client.get_speeches(page_size=1)

        assert len(speeches) > 0, "Should have at least one speech"

        speech_meta = speeches[0]
        speech_id = speech_meta.get("otid") or speech_meta.get("id")
        title = speech_meta.get("title", "Untitled")

        # Get full speech
        speech = client.get_speech(speech_id)

        # Format and save
        transcript_data = client.format_transcript_json(speech)

        filepath = output_dir / f"latest_{speech_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(transcript_data, f, indent=2, ensure_ascii=False)

        # Also save raw speech data for debugging
        raw_filepath = output_dir / f"latest_{speech_id}_raw.json"
        with open(raw_filepath, "w", encoding="utf-8") as f:
            json.dump(speech, f, indent=2, ensure_ascii=False, default=str)

        print(f"\n      Latest transcript: {title}")
        print(f"      Segments: {transcript_data.get('segment_count', 0)}")
        print(f"      Speakers: {transcript_data.get('speaker_names', [])}")
        print(f"      Saved to: {filepath}")
        print(f"      Raw data: {raw_filepath}")

        # Validate structure
        assert transcript_data["otter_id"] == str(speech_id) or transcript_data["otter_id"] == speech_id
        assert "segments" in transcript_data
        assert "full_text" in transcript_data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
