#!/usr/bin/env python3
"""
Local testing script for task-consolidator.

This script allows you to test the consolidator locally without deploying to GCP.
It can rebuild the consolidated file from existing tasks in your bucket.

Usage:
    # First, set up environment
    cd task-consolidator
    python -m venv venv
    source venv/bin/activate  # or venv\Scripts\activate on Windows
    pip install -r requirements.txt python-dotenv

    # Create .env file with:
    # GCS_BUCKET=your-bucket-name

    # Run tests
    python local_test.py --rebuild          # Rebuild from all task files
    python local_test.py --rebuild --dry-run  # See what would be rebuilt
    python local_test.py --get              # Get all consolidated tasks
    python local_test.py --get --topic Work # Filter by topic
    python local_test.py --get --summary    # Get summary only
"""

import argparse
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("Note: python-dotenv not installed. Using environment variables only.")
    print("Install with: pip install python-dotenv")

# Import after loading env vars
from google.cloud import storage


def get_bucket_name():
    """Get bucket name from environment."""
    bucket = os.environ.get("GCS_BUCKET")
    if not bucket:
        print("Error: GCS_BUCKET environment variable not set")
        print("Set it in .env file or environment")
        sys.exit(1)
    return bucket


def list_task_files(bucket_name: str):
    """List all task files in the bucket."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    print(f"\nTask files in gs://{bucket_name}/tasks/:")
    print("-" * 60)

    task_files = []
    blobs = bucket.list_blobs(prefix="tasks/")

    for blob in blobs:
        if blob.name.endswith(".json") and "consolidated" not in blob.name:
            task_files.append(blob.name)
            # Get the file to show task count
            try:
                content = blob.download_as_text()
                data = json.loads(content)
                task_count = data.get("task_count", 0)
                title = data.get("source", {}).get("transcript_title", "Unknown")
                print(f"  {blob.name}")
                print(f"    Title: {title}, Tasks: {task_count}")
            except:
                print(f"  {blob.name} (could not read)")

    print("-" * 60)
    print(f"Total: {len(task_files)} task files")
    return task_files


def rebuild_consolidated(bucket_name: str, dry_run: bool = False):
    """Rebuild the consolidated file from all task files."""
    from main import (
        get_consolidated_tasks, save_consolidated_tasks,
        get_task_file, add_tasks_from_source, CONSOLIDATED_FILE
    )

    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    # List all task files
    task_files = []
    blobs = bucket.list_blobs(prefix="tasks/")

    for blob in blobs:
        if blob.name == CONSOLIDATED_FILE or not blob.name.endswith(".json"):
            continue
        task_files.append(blob.name)

    print(f"\nFound {len(task_files)} task files to consolidate")

    if dry_run:
        print("\n[DRY RUN] Would consolidate these files:")
        for f in task_files:
            print(f"  - {f}")
        return

    # Start fresh
    consolidated = {
        "version": "1.0",
        "description": "Consolidated tasks from all transcripts",
        "last_updated": None,
        "total_tasks": 0,
        "sources": {},
        "tasks": [],
        "by_topic": {},
        "by_assignee": {},
        "by_priority": {"high": [], "medium": [], "low": []}
    }

    # Process each task file
    processed = 0
    for blob_path in task_files:
        task_file = get_task_file(bucket_name, blob_path)
        if not task_file or not task_file.get("tasks"):
            print(f"  Skipping {blob_path} (no tasks)")
            continue

        # Build event-like structure from task file
        source = task_file.get("source", {})
        event = {
            "transcript_id": source.get("transcript_id", blob_path),
            "transcript_title": source.get("transcript_title", "Untitled"),
            "transcript_topic": source.get("transcript_topic", "General"),
            "transcript_created_at": source.get("transcript_created_at", ""),
            "gcs_bucket": bucket_name,
            "gcs_blob": blob_path,
            "gcs_path": f"gs://{bucket_name}/{blob_path}"
        }

        consolidated = add_tasks_from_source(consolidated, task_file, event)
        processed += 1
        print(f"  Processed {blob_path}: {len(task_file.get('tasks', []))} tasks")

    # Save the rebuilt consolidated file
    save_consolidated_tasks(bucket_name, consolidated)

    print(f"\nConsolidation complete!")
    print(f"  Files processed: {processed}")
    print(f"  Total tasks: {consolidated['total_tasks']}")
    print(f"  Sources: {len(consolidated['sources'])}")
    print(f"  Topics: {list(consolidated['by_topic'].keys())}")
    print(f"  Assignees: {list(consolidated['by_assignee'].keys())}")
    print(f"\nSaved to: gs://{bucket_name}/{CONSOLIDATED_FILE}")


def get_tasks(bucket_name: str, topic: str = None, assignee: str = None,
              priority: str = None, summary: bool = False, limit: int = 100):
    """Get and display consolidated tasks."""
    from main import get_consolidated_tasks

    consolidated = get_consolidated_tasks(bucket_name)

    if summary:
        print("\n=== Task Summary ===")
        print(f"Total tasks: {consolidated.get('total_tasks', 0)}")
        print(f"Sources: {len(consolidated.get('sources', {}))}")
        print(f"Last updated: {consolidated.get('last_updated', 'Never')}")
        print(f"\nTopics ({len(consolidated.get('by_topic', {}))}):")
        for t, tasks in sorted(consolidated.get("by_topic", {}).items()):
            print(f"  - {t}: {len(tasks)} tasks")
        print(f"\nAssignees ({len(consolidated.get('by_assignee', {}))}):")
        for a, tasks in sorted(consolidated.get("by_assignee", {}).items()):
            print(f"  - {a}: {len(tasks)} tasks")
        print(f"\nPriorities:")
        for p, tasks in consolidated.get("by_priority", {}).items():
            print(f"  - {p}: {len(tasks)} tasks")
        return

    # Filter tasks
    tasks = consolidated.get("tasks", [])

    if topic:
        tasks = [t for t in tasks if t.get("primary_topic", "").startswith(topic)]

    if assignee:
        if assignee.lower() == "unassigned":
            tasks = [t for t in tasks if not t.get("assignee")]
        else:
            tasks = [t for t in tasks if (t.get("assignee") or "").lower() == assignee.lower()]

    if priority:
        tasks = [t for t in tasks if t.get("priority", "").lower() == priority.lower()]

    tasks = tasks[:limit]

    print(f"\n=== Tasks ({len(tasks)} of {consolidated.get('total_tasks', 0)}) ===\n")

    for i, task in enumerate(tasks, 1):
        print(f"{i}. {task.get('description', 'No description')}")
        print(f"   Topic: {task.get('primary_topic', 'Unknown')}")
        if task.get("assignee"):
            print(f"   Assignee: {task['assignee']}")
        if task.get("deadline"):
            print(f"   Deadline: {task['deadline']}")
        print(f"   Priority: {task.get('priority', 'medium')}")
        print(f"   Source: {task.get('source_transcript_title', 'Unknown')}")
        print()


def view_consolidated_raw(bucket_name: str):
    """View the raw consolidated JSON file."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob("tasks/consolidated_tasks.json")

    if not blob.exists():
        print("Consolidated file does not exist yet.")
        print("Run with --rebuild to create it.")
        return

    content = blob.download_as_text()
    data = json.loads(content)
    print(json.dumps(data, indent=2))


def main():
    parser = argparse.ArgumentParser(
        description="Local testing for task-consolidator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python local_test.py --list              # List all task files
  python local_test.py --rebuild           # Rebuild consolidated file
  python local_test.py --rebuild --dry-run # See what would be rebuilt
  python local_test.py --get               # Get all tasks
  python local_test.py --get --topic Work  # Filter by topic
  python local_test.py --get --summary     # Get summary only
  python local_test.py --raw               # View raw consolidated JSON
        """
    )

    parser.add_argument("--list", action="store_true", help="List all task files in bucket")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild consolidated file from all tasks")
    parser.add_argument("--get", action="store_true", help="Get consolidated tasks")
    parser.add_argument("--raw", action="store_true", help="View raw consolidated JSON")
    parser.add_argument("--dry-run", action="store_true", help="Don't make changes (with --rebuild)")
    parser.add_argument("--topic", type=str, help="Filter by topic prefix")
    parser.add_argument("--assignee", type=str, help="Filter by assignee")
    parser.add_argument("--priority", type=str, choices=["high", "medium", "low"], help="Filter by priority")
    parser.add_argument("--summary", action="store_true", help="Show summary only")
    parser.add_argument("--limit", type=int, default=100, help="Max tasks to show")

    args = parser.parse_args()

    bucket_name = get_bucket_name()
    print(f"Using bucket: {bucket_name}")

    if args.list:
        list_task_files(bucket_name)
    elif args.rebuild:
        rebuild_consolidated(bucket_name, dry_run=args.dry_run)
    elif args.get:
        get_tasks(bucket_name, topic=args.topic, assignee=args.assignee,
                  priority=args.priority, summary=args.summary, limit=args.limit)
    elif args.raw:
        view_consolidated_raw(bucket_name)
    else:
        # Default: show summary
        print("\nNo action specified. Showing task file list...")
        list_task_files(bucket_name)
        print("\nUse --help to see available commands")


if __name__ == "__main__":
    main()
