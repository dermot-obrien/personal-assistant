"""
Local testing script for Otter sync function.

Usage:
    1. Copy .env.example to .env and fill in your credentials
    2. Run: python local_test.py
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def test_otter_connection():
    """Test connection to Otter.ai API."""
    from main import OtterClient

    email = os.environ.get("OTTER_EMAIL")
    password = os.environ.get("OTTER_PASSWORD")

    if not email or not password:
        print("Error: Set OTTER_EMAIL and OTTER_PASSWORD in .env file")
        return

    print(f"Testing connection for: {email}")

    client = OtterClient(email, password)

    try:
        client.authenticate()
        print("[OK] Authentication successful")

        speeches = client.get_speeches(page_size=5)
        print(f"[OK] Retrieved {len(speeches)} recent conversations")

        if speeches:
            first = speeches[0]
            print(f"\nMost recent conversation:")
            print(f"  Title: {first.get('title')}")
            # Otter uses 'otid' for speech ID
            speech_id = first.get('otid') or first.get('id')
            print(f"  ID: {speech_id}")
            print(f"  Available keys: {list(first.keys())}")

            # Get full transcript
            full_speech = client.get_speech(speech_id)

            # Debug: print timestamp-related fields
            print(f"\n  Timestamp fields:")
            for key in ['created_at', 'start_time', 'end_time', 'created', 'timestamp', 'start_epoch_time']:
                if key in full_speech:
                    val = full_speech[key]
                    print(f"    {key}: {val}")
                    # Try to parse as timestamp
                    if isinstance(val, (int, float)) and val > 0:
                        from datetime import datetime
                        try:
                            # Try milliseconds
                            dt_ms = datetime.fromtimestamp(val / 1000)
                            print(f"      -> as ms: {dt_ms}")
                        except:
                            pass
                        try:
                            # Try seconds
                            dt_s = datetime.fromtimestamp(val)
                            print(f"      -> as sec: {dt_s}")
                        except:
                            pass

            # Also check speech_meta for comparison
            print(f"\n  Speech meta timestamp fields:")
            for key in ['created_at', 'start_time', 'end_time', 'created', 'timestamp', 'start_epoch_time']:
                if key in first:
                    print(f"    {key}: {first[key]}")

            transcript_data = client.format_transcript_json(full_speech)
            print(f"\n  Transcript preview: {transcript_data.get('segment_count')} segments")

        # Test folder mapping
        print(f"\n--- Folder Mapping Debug ---")

        # First, check the 'folder' field directly on recent speeches
        print(f"\nDirect 'folder' field on recent speeches:")
        for speech in speeches[:5]:
            if speech is None:
                continue
            sid = speech.get('otid') or speech.get('id')
            title = speech.get('title', 'Untitled')[:40]
            folder_field = speech.get('folder')
            print(f"  - {title}...")
            print(f"      folder field: {folder_field}")
            if isinstance(folder_field, dict):
                print(f"      folder_name: {folder_field.get('folder_name')}")
                print(f"      folder_id: {folder_field.get('id')}")

        # Show all folders
        folders = client.get_folders()
        print(f"\nOtter folders ({len(folders)}):")
        for folder in folders:
            folder_id = folder.get('id')
            folder_name = folder.get('folder_name')
            print(f"  - {folder_name} (id: {folder_id})")

        # Build folder map from iterating folders
        folder_map = client.get_folder_speech_mapping()
        print(f"\n[OK] Built folder mapping for {len(folder_map)} speeches via folder iteration")

        # Compare: direct folder field vs folder iteration
        print(f"\nComparison - Direct folder field vs Folder iteration:")
        for speech in speeches[:5]:
            if speech is None:
                continue
            sid = speech.get('otid') or speech.get('id')
            title = speech.get('title', 'Untitled')[:30]

            # Direct folder field
            folder_field = speech.get('folder')
            direct_folder = folder_field.get('folder_name') if isinstance(folder_field, dict) else None

            # Folder iteration map
            iterated_folder = folder_map.get(str(sid), "General")

            match = "OK" if direct_folder == iterated_folder else "MISMATCH"
            print(f"  [{match}] {title}...")
            print(f"       Direct: {direct_folder}, Iterated: {iterated_folder}")

    except Exception as e:
        print(f"[ERROR] Error: {e}")


def test_gcs_connection():
    """Test connection to Google Cloud Storage."""
    from google.cloud import storage

    bucket_name = os.environ.get("GCS_BUCKET")

    if not bucket_name:
        print("Error: Set GCS_BUCKET in .env file")
        return

    print(f"\nTesting GCS bucket: {bucket_name}")

    try:
        client = storage.Client()
        bucket = client.bucket(bucket_name)

        if bucket.exists():
            print("[OK] Bucket exists and is accessible")

            blobs = list(bucket.list_blobs(prefix="transcripts/", max_results=5))
            print(f"✓ Found {len(blobs)} transcript files")

        else:
            print("[ERROR] Bucket does not exist")

    except Exception as e:
        print(f"[ERROR] Error: {e}")


if __name__ == "__main__":
    print("=== Otter Sync Local Test ===\n")
    test_otter_connection()
    test_gcs_connection()
