"""
Local testing script for Plaud sync function.

Usage:
    1. Copy .env.example to .env and fill in your credentials
    2. Run: python local_test.py
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Note: python-dotenv not installed. Using environment variables only.")


def test_plaud_connection():
    """Test connection to Plaud API."""
    from main import PlaudClient

    token = os.environ.get("PLAUD_ACCESS_TOKEN")

    if not token:
        print("Error: Set PLAUD_ACCESS_TOKEN in .env file or environment")
        print("\nRun 'python get_token.py' for instructions on getting your token.")
        return False

    print(f"Testing connection with token: {token[:20]}...")

    client = PlaudClient(token)

    try:
        print("\nAttempting to fetch recordings...")
        recordings = client.get_recordings(page_size=5)

        # Handle different response structures
        files = (recordings.get("files") or
                recordings.get("data") or
                recordings.get("recordings") or
                recordings.get("items") or
                [])

        if isinstance(recordings, list):
            files = recordings

        print(f"✓ Retrieved {len(files)} recordings")

        if files:
            first = files[0]
            file_id = first.get("id") or first.get("file_id")
            title = first.get("title") or first.get("name") or "Untitled"

            print(f"\nMost recent recording:")
            print(f"  Title: {title}")
            print(f"  ID: {file_id}")

            # Try to get transcript
            print("\nFetching transcript...")
            transcript = client.get_transcript(file_id)
            summary = client.get_summary(file_id)

            if transcript:
                print("✓ Transcript retrieved")
            else:
                print("○ No transcript available (or different endpoint)")

            if summary:
                print("✓ Summary retrieved")
            else:
                print("○ No summary available")

            # Format transcript
            formatted = client.format_transcript(first, transcript, summary)
            print(f"\n--- Formatted transcript preview ({len(formatted)} chars) ---")
            print(formatted[:500])
            if len(formatted) > 500:
                print("...")
            print("--- End preview ---")

        return True

    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_gcs_connection():
    """Test connection to Google Cloud Storage."""
    try:
        from google.cloud import storage
    except ImportError:
        print("\nSkipping GCS test - google-cloud-storage not installed")
        return

    bucket_name = os.environ.get("GCS_BUCKET")

    if not bucket_name:
        print("\nSkipping GCS test - GCS_BUCKET not set in .env")
        return

    print(f"\nTesting GCS bucket: {bucket_name}")

    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)

        if bucket.exists():
            print("✓ Bucket exists and is accessible")

            blobs = list(bucket.list_blobs(prefix="plaud-transcripts/", max_results=5))
            print(f"✓ Found {len(blobs)} transcript files")

            for blob in blobs[:3]:
                print(f"  - {blob.name}")

        else:
            print("○ Bucket does not exist (will be created on deploy)")

    except Exception as e:
        print(f"✗ GCS Error: {e}")


def explore_api():
    """Explore the Plaud API to discover endpoints."""
    from main import PlaudClient

    token = os.environ.get("PLAUD_ACCESS_TOKEN")
    if not token:
        print("Error: Set PLAUD_ACCESS_TOKEN")
        return

    client = PlaudClient(token)

    print("\n=== API Exploration ===\n")

    # Try various endpoints to discover the API structure
    test_endpoints = [
        ("GET", "/apis/user"),
        ("GET", "/apis/files"),
        ("GET", "/apis/v1/files"),
        ("GET", "/files"),
        ("GET", "/apis/recordings"),
        ("GET", "/apis/me"),
        ("GET", "/apis/user/info"),
    ]

    for method, endpoint in test_endpoints:
        url = f"{client.BASE_URL}{endpoint}"
        try:
            if method == "GET":
                resp = client.session.get(url, params={"page_size": 1})
            else:
                resp = client.session.post(url)

            status = resp.status_code
            if status == 200:
                data = resp.json()
                keys = list(data.keys()) if isinstance(data, dict) else f"[list of {len(data)}]"
                print(f"✓ {method} {endpoint} -> {status} - keys: {keys}")
            else:
                print(f"✗ {method} {endpoint} -> {status}")

        except Exception as e:
            print(f"✗ {method} {endpoint} -> Error: {e}")


if __name__ == "__main__":
    print("=== Plaud Sync Local Test ===\n")

    if len(sys.argv) > 1 and sys.argv[1] == "--explore":
        explore_api()
    else:
        success = test_plaud_connection()
        if success:
            test_gcs_connection()
        else:
            print("\n💡 Tip: Run 'python get_token.py' to see how to get your token")
            print("💡 Tip: Run 'python local_test.py --explore' to explore API endpoints")
