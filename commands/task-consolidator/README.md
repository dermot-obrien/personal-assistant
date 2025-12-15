# Task Consolidator

Google Cloud Function that consolidates all extracted tasks into a single master file with comprehensive metadata.

## Overview

This function listens to the `task-extracted-events` Pub/Sub topic (published by `task-extractor`) and maintains a consolidated view of all tasks across all transcripts. This enables:

- Unified task list across all conversations
- Filtering by topic, assignee, or priority
- Quick access to all tasks via HTTP endpoint
- Indexes for efficient lookups

## Architecture

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
│  task-extractor │────▶│ task-extracted-events│────▶│  task-consolidator  │
│                 │     │     (Pub/Sub)        │     │                     │
│ Extracts tasks  │     │                      │     │ Consolidates tasks  │
│ from transcript │     │  Event: tasks.       │     │ into single file    │
└─────────────────┘     │    extracted         │     └─────────────────────┘
                        └──────────────────────┘              │
                                                              ▼
                                                    ┌─────────────────────┐
                                                    │   GCS Bucket        │
                                                    │ tasks/consolidated_ │
                                                    │   tasks.json        │
                                                    └─────────────────────┘
```

## Consolidated File Structure

The consolidated file (`tasks/consolidated_tasks.json`) contains:

```json
{
  "version": "1.0",
  "description": "Consolidated tasks from all transcripts",
  "last_updated": "2024-01-15T14:30:00+13:00",
  "total_tasks": 47,
  "sources": {
    "abc123": {
      "transcript_id": "abc123",
      "transcript_title": "Team Meeting",
      "transcript_topic": "Work/Meetings",
      "transcript_created_at": "2024-01-15T10:30:00+13:00",
      "tasks_gcs_path": "gs://bucket/tasks/2024-01-15_Team_Meeting_abc123.json",
      "task_count": 5,
      "extracted_at": "2024-01-15T11:00:30+13:00",
      "consolidated_at": "2024-01-15T11:00:35+13:00",
      "summary": "Meeting covered budget review and hiring plans"
    }
  },
  "tasks": [
    {
      "description": "Review Q4 budget proposal",
      "assignee": "John",
      "deadline": "Friday",
      "primary_topic": "Work/Finance",
      "secondary_topics": ["Work/Meetings"],
      "priority": "high",
      "context": "Discussed during budget review section",
      "source_transcript_id": "abc123",
      "source_transcript_title": "Team Meeting",
      "source_transcript_topic": "Work/Meetings",
      "source_transcript_created_at": "2024-01-15T10:30:00+13:00",
      "consolidated_at": "2024-01-15T11:00:35+13:00"
    }
  ],
  "by_topic": {
    "Work/Finance": [{"index": 0, "description": "Review Q4 budget...", ...}],
    "Work/Projects": [...]
  },
  "by_assignee": {
    "John": [{"index": 0, "description": "Review Q4 budget...", ...}],
    "Unassigned": [...]
  },
  "by_priority": {
    "high": [...],
    "medium": [...],
    "low": [...]
  }
}
```

## Deployment

### Prerequisites

- Google Cloud SDK (`gcloud`) installed and configured
- GCP project with billing enabled
- `task-extractor` deployed and publishing to `task-extracted-events` topic

### Deploy

```bash
# Set required environment variables
export GCP_PROJECT=your-project-id
export GCS_BUCKET=your-bucket-name

# Deploy (bash)
./deploy.sh

# Deploy (PowerShell)
.\deploy.ps1
```

This deploys three Cloud Functions:

1. **task-consolidator** - Pub/Sub triggered, automatically consolidates new tasks
2. **task-consolidator-rebuild** - HTTP triggered, rebuilds from all task files
3. **task-consolidator-get** - HTTP triggered, retrieves tasks with filtering

## Usage

### Automatic Consolidation

The Pub/Sub function automatically runs when `task-extractor` finishes extracting tasks. No manual intervention needed.

### Rebuild Consolidated File

Rebuild from all existing task files (useful for initial setup or recovery):

```bash
# Dry run - see what would be consolidated
curl "https://REGION-PROJECT.cloudfunctions.net/task-consolidator-rebuild?dry_run=true"

# Rebuild
curl "https://REGION-PROJECT.cloudfunctions.net/task-consolidator-rebuild"
```

### Query Tasks

```bash
# Get all tasks
curl "https://REGION-PROJECT.cloudfunctions.net/task-consolidator-get"

# Get summary only
curl "https://REGION-PROJECT.cloudfunctions.net/task-consolidator-get?format=summary"

# Filter by topic (prefix match)
curl "https://REGION-PROJECT.cloudfunctions.net/task-consolidator-get?topic=Work"
curl "https://REGION-PROJECT.cloudfunctions.net/task-consolidator-get?topic=Work/Projects"

# Filter by assignee
curl "https://REGION-PROJECT.cloudfunctions.net/task-consolidator-get?assignee=John"
curl "https://REGION-PROJECT.cloudfunctions.net/task-consolidator-get?assignee=Unassigned"

# Filter by priority
curl "https://REGION-PROJECT.cloudfunctions.net/task-consolidator-get?priority=high"

# Combine filters
curl "https://REGION-PROJECT.cloudfunctions.net/task-consolidator-get?topic=Work&priority=high&limit=10"

# Get tasks grouped by topic
curl "https://REGION-PROJECT.cloudfunctions.net/task-consolidator-get?format=by_topic"

# Get tasks grouped by assignee
curl "https://REGION-PROJECT.cloudfunctions.net/task-consolidator-get?format=by_assignee"

# Get tasks grouped by priority
curl "https://REGION-PROJECT.cloudfunctions.net/task-consolidator-get?format=by_priority"
```

### View Logs

```bash
# View consolidator logs
gcloud functions logs read task-consolidator --region=us-central1

# View rebuild endpoint logs
gcloud functions logs read task-consolidator-rebuild --region=us-central1
```

### Direct GCS Access

```bash
# View consolidated file
gsutil cat gs://your-bucket/tasks/consolidated_tasks.json | jq .

# View specific source info
gsutil cat gs://your-bucket/tasks/consolidated_tasks.json | jq '.sources["abc123"]'

# Count tasks by topic
gsutil cat gs://your-bucket/tasks/consolidated_tasks.json | jq '.by_topic | to_entries | map({topic: .key, count: (.value | length)})'
```

## Local Development

```bash
# Set up virtual environment
cd task-consolidator
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt python-dotenv

# Create .env file
echo "GCS_BUCKET=your-bucket-name" > .env

# List task files
python local_test.py --list

# Rebuild consolidated file
python local_test.py --rebuild

# Dry run rebuild
python local_test.py --rebuild --dry-run

# Get tasks
python local_test.py --get
python local_test.py --get --topic Work
python local_test.py --get --summary

# View raw JSON
python local_test.py --raw
```

## Event Format

### Input Event (from task-extractor)

```json
{
  "event_type": "tasks.extracted",
  "transcript_id": "abc123",
  "transcript_title": "Team Meeting",
  "transcript_topic": "Work/Meetings",
  "task_count": 5,
  "gcs_path": "gs://bucket/tasks/2024-01-15_Team_Meeting_abc123.json",
  "gcs_bucket": "bucket",
  "gcs_blob": "tasks/2024-01-15_Team_Meeting_abc123.json",
  "transcript_created_at": "2024-01-15T10:30:00+13:00",
  "extracted_at": "2024-01-15T11:00:30+13:00"
}
```

## Behavior Notes

### Idempotency

- If tasks from the same transcript are received again, the old tasks are replaced with new ones
- This ensures re-running task-extractor produces correct consolidated results
- No duplicate tasks from the same source

### Index Rebuilding

- Indexes (`by_topic`, `by_assignee`, `by_priority`) are rebuilt on every update
- This ensures consistency after task additions/updates

### Zero-Task Files

- Task files with no tasks are skipped during consolidation
- They don't appear in the sources list

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GCS_BUCKET` | GCS bucket for task files | Required |
| `LOCAL_TIMEZONE` | Timezone for timestamps | Pacific/Auckland |

### Function Settings

| Function | Memory | Timeout | Max Instances |
|----------|--------|---------|---------------|
| task-consolidator | 256MB | 60s | 5 |
| task-consolidator-rebuild | 512MB | 300s | 1 |
| task-consolidator-get | 256MB | 30s | 10 |
