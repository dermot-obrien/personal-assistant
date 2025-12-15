"""
Local testing script for Task Extractor function.

This script simulates Pub/Sub events to test the task extraction locally
without deploying to Cloud Functions.

Usage:
    1. Copy .env.example to .env and fill in your credentials
    2. Run: python local_test.py

Options:
    python local_test.py --list          # List available transcripts
    python local_test.py --transcript ID # Process specific transcript
    python local_test.py --latest        # Process most recent transcript
    python local_test.py --dry-run       # Extract tasks without saving
"""

import argparse
import base64
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

# Load environment from .env file if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Set up environment before importing main
os.environ.setdefault("LOCAL_TIMEZONE", "Pacific/Auckland")

LOCAL_TIMEZONE = ZoneInfo(os.environ.get("LOCAL_TIMEZONE", "Pacific/Auckland"))


def get_gcs_client():
    """Get Google Cloud Storage client."""
    from google.cloud import storage
    return storage.Client()


def list_transcripts(bucket_name: str, limit: int = 10):
    """List available transcripts in the bucket."""
    client = get_gcs_client()
    bucket = client.bucket(bucket_name)

    print(f"\nListing transcripts in gs://{bucket_name}/transcripts/")
    print("-" * 60)

    blobs = list(bucket.list_blobs(prefix="transcripts/", max_results=limit))

    if not blobs:
        print("No transcripts found.")
        return []

    transcripts = []
    for blob in blobs:
        if not blob.name.endswith(".json"):
            continue

        # Try to extract info from filename
        filename = blob.name.replace("transcripts/", "")
        transcripts.append({
            "path": blob.name,
            "filename": filename,
            "size": blob.size,
            "updated": blob.updated
        })

    # Sort by updated time (most recent first)
    transcripts.sort(key=lambda x: x["updated"], reverse=True)

    for i, t in enumerate(transcripts[:limit]):
        print(f"{i+1}. {t['filename']}")
        print(f"   Size: {t['size']:,} bytes | Updated: {t['updated']}")

    return transcripts


def get_transcript_details(bucket_name: str, blob_path: str) -> dict:
    """Download and parse a transcript to get details."""
    client = get_gcs_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    content = blob.download_as_text()
    return json.loads(content)


def create_mock_cloud_event(transcript_data: dict, bucket_name: str, blob_path: str):
    """Create a mock CloudEvent that simulates a Pub/Sub message."""

    # Extract transcript ID from filename or data
    transcript_id = transcript_data.get("otter_id", "unknown")
    if transcript_id == "unknown":
        # Try to extract from filename
        filename = blob_path.split("/")[-1]
        parts = filename.replace(".json", "").split("_")
        if parts:
            transcript_id = parts[-1]

    # Build the event payload (same format as otter-sync publishes)
    event_payload = {
        "event_type": "transcript.created",
        "otter_id": transcript_id,
        "title": transcript_data.get("title", "Untitled"),
        "topic": transcript_data.get("topic", "General"),
        "gcs_path": f"gs://{bucket_name}/{blob_path}",
        "gcs_bucket": bucket_name,
        "gcs_blob": blob_path,
        "created_at": transcript_data.get("created_at", ""),
        "synced_at": datetime.now(LOCAL_TIMEZONE).isoformat()
    }

    # Encode as base64 (how Pub/Sub delivers messages)
    message_data = base64.b64encode(
        json.dumps(event_payload).encode("utf-8")
    ).decode("utf-8")

    # Create mock CloudEvent structure
    class MockCloudEvent:
        def __init__(self, data):
            self.data = data

    return MockCloudEvent({
        "message": {
            "data": message_data
        }
    })


def test_extraction_dry_run(bucket_name: str, blob_path: str):
    """Test task extraction without saving results."""
    from main import (
        get_transcript_content,
        get_topic_taxonomy,
        extract_tasks_with_gemini
    )

    project_id = os.environ.get("GCP_PROJECT")
    if not project_id:
        print("Error: GCP_PROJECT environment variable is required")
        return

    print(f"\n=== Dry Run: Task Extraction ===")
    print(f"Transcript: {blob_path}")
    print("-" * 60)

    # Load transcript
    print("\n1. Loading transcript...")
    transcript = get_transcript_content(bucket_name, blob_path)
    print(f"   Title: {transcript.get('title')}")
    print(f"   Topic: {transcript.get('topic')}")
    print(f"   Segments: {len(transcript.get('segments', []))}")

    # Load taxonomy
    print("\n2. Loading topic taxonomy...")
    taxonomy = get_topic_taxonomy(bucket_name)
    print(f"   Topics: {len(taxonomy.get('topics', []))}")

    # Extract tasks
    print("\n3. Extracting tasks with Gemini...")
    print("   (This may take a few seconds)")

    tasks_result = extract_tasks_with_gemini(transcript, project_id, taxonomy)

    tasks = tasks_result.get("tasks", [])
    print(f"\n   Found {len(tasks)} tasks")

    if tasks:
        print("\n=== Extracted Tasks ===")
        for i, task in enumerate(tasks, 1):
            print(f"\n{i}. {task.get('description')}")
            print(f"   Topic: {task.get('primary_topic')}")
            print(f"   Priority: {task.get('priority')}")
            if task.get("assignee"):
                print(f"   Assignee: {task.get('assignee')}")
            if task.get("deadline"):
                print(f"   Deadline: {task.get('deadline')}")
            if task.get("context"):
                print(f"   Context: {task.get('context')[:100]}...")

    if tasks_result.get("summary"):
        print(f"\nSummary: {tasks_result.get('summary')}")

    if tasks_result.get("error"):
        print(f"\nError: {tasks_result.get('error')}")


def test_full_processing(bucket_name: str, blob_path: str):
    """Test full event processing (saves results to GCS)."""
    from main import process_transcript_event

    print(f"\n=== Full Processing Test ===")
    print(f"Transcript: {blob_path}")
    print("-" * 60)

    # Load transcript to create mock event
    transcript = get_transcript_details(bucket_name, blob_path)

    # Create mock cloud event
    cloud_event = create_mock_cloud_event(transcript, bucket_name, blob_path)

    print(f"\nEvent payload:")
    event_data = json.loads(
        base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    )
    print(json.dumps(event_data, indent=2))

    print("\nProcessing event...")
    print("-" * 60)

    try:
        process_transcript_event(cloud_event)
        print("\n[OK] Processing completed successfully")
    except Exception as e:
        print(f"\n[ERROR] Processing failed: {e}")
        raise


def test_state_file(bucket_name: str):
    """Check the current state file."""
    from main import get_processed_tasks_state

    print(f"\n=== State File Check ===")
    print("-" * 60)

    state = get_processed_tasks_state(bucket_name)

    if not state:
        print("State file is empty or doesn't exist.")
        print("No transcripts have been processed yet.")
    else:
        print(f"Processed transcripts: {len(state)}")
        print("\nRecent entries:")
        for transcript_id, tasks_path in list(state.items())[-5:]:
            print(f"  {transcript_id}: {tasks_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Local testing for Task Extractor function"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List available transcripts"
    )
    parser.add_argument(
        "--transcript", "-t",
        type=str,
        help="Process specific transcript by path or ID"
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Process the most recent transcript"
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Extract tasks without saving to GCS"
    )
    parser.add_argument(
        "--state",
        action="store_true",
        help="Show current state file contents"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of transcripts to list (default: 10)"
    )

    args = parser.parse_args()

    # Get bucket name
    bucket_name = os.environ.get("GCS_BUCKET")
    if not bucket_name:
        print("Error: GCS_BUCKET environment variable is required")
        print("Set it with: export GCS_BUCKET=your-bucket-name")
        sys.exit(1)

    project_id = os.environ.get("GCP_PROJECT")
    if not project_id:
        print("Error: GCP_PROJECT environment variable is required")
        print("Set it with: export GCP_PROJECT=your-project-id")
        sys.exit(1)

    print("=== Task Extractor Local Test ===")
    print(f"Project: {project_id}")
    print(f"Bucket: {bucket_name}")

    if args.state:
        test_state_file(bucket_name)
        return

    if args.list:
        list_transcripts(bucket_name, args.limit)
        return

    # Determine which transcript to process
    blob_path = None

    if args.transcript:
        # Check if it's a full path or just an ID
        if args.transcript.startswith("transcripts/"):
            blob_path = args.transcript
        else:
            # Search for matching transcript
            transcripts = list_transcripts(bucket_name, 50)
            for t in transcripts:
                if args.transcript in t["filename"] or args.transcript in t["path"]:
                    blob_path = t["path"]
                    break

            if not blob_path:
                print(f"\nNo transcript found matching: {args.transcript}")
                sys.exit(1)

    elif args.latest:
        transcripts = list_transcripts(bucket_name, 1)
        if transcripts:
            blob_path = transcripts[0]["path"]
        else:
            print("No transcripts found in bucket")
            sys.exit(1)

    else:
        # Default: show help and list transcripts
        print("\nUsage examples:")
        print("  python local_test.py --list              # List transcripts")
        print("  python local_test.py --latest --dry-run  # Test latest transcript")
        print("  python local_test.py --latest            # Process latest transcript")
        print("  python local_test.py --transcript ID     # Process specific transcript")
        print("  python local_test.py --state             # Show processing state")
        print()
        list_transcripts(bucket_name, 5)
        return

    # Process the transcript
    if args.dry_run:
        test_extraction_dry_run(bucket_name, blob_path)
    else:
        test_full_processing(bucket_name, blob_path)


if __name__ == "__main__":
    main()
