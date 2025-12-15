# Task Extractor

A Google Cloud Function that listens for new Otter transcripts and automatically extracts tasks and action items using Gemini AI.

## Architecture

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   otter-sync    │─────▶│    Pub/Sub      │─────▶│ task-extractor  │
│  (transcripts)  │      │    (events)     │      │    (Gemini)     │
└─────────────────┘      └─────────────────┘      └────────┬────────┘
                                                           │
                                                           ▼
                                                  ┌─────────────────┐
                                                  │  Cloud Storage  │
                                                  │    (tasks/)     │
                                                  └─────────────────┘
```

## How It Works

1. **Trigger**: Receives Pub/Sub messages from `otter-sync` when new transcripts are uploaded
2. **Download**: Fetches the full transcript JSON from Cloud Storage
3. **Extract**: Uses Gemini 1.5 Flash to analyze the transcript and identify tasks
4. **Classify**: Assigns primary and secondary topic categories to each task
5. **Save**: Stores extracted tasks as JSON in the `tasks/` folder

## Task Output Format

Each task record includes:

```json
{
  "source": {
    "transcript_id": "abc123",
    "transcript_title": "Team Meeting",
    "transcript_topic": "Work/Meetings",
    "transcript_created_at": "2024-01-15T10:30:00+13:00"
  },
  "extracted_at": "2024-01-15T11:00:00+13:00",
  "task_count": 3,
  "tasks": [
    {
      "description": "Review Q4 budget proposal",
      "assignee": "John",
      "deadline": "Friday",
      "primary_topic": "Work/Finance",
      "secondary_topics": ["Work/Meetings", "Work/Planning"],
      "priority": "high",
      "context": "Discussed during budget review section"
    }
  ],
  "summary": "Meeting covered budget review, project updates, and hiring plans"
}
```

## Prerequisites

- Google Cloud project with billing enabled
- `otter-sync` function already deployed
- Vertex AI API enabled

## Deployment

### 1. Set Environment Variables

```bash
export GCP_PROJECT=your-project-id
export GCP_REGION=us-central1
export GCS_BUCKET=your-bucket-name
```

### 2. Deploy

**macOS/Linux:**
```bash
cd task-extractor
chmod +x deploy.sh
./deploy.sh
```

**Windows PowerShell:**
```powershell
cd task-extractor
.\deploy.ps1
```

### 3. Test

Upload a new transcript via `otter-sync`, then check the logs:

```bash
gcloud functions logs read task-extractor --region=$GCP_REGION --limit=20
```

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `GCP_PROJECT` | Google Cloud project ID | Required |
| `GCS_BUCKET` | GCS bucket for transcripts/tasks | Required |
| `LOCAL_TIMEZONE` | Timezone for timestamps | `Pacific/Auckland` |

## Topic Taxonomy

The extractor uses an external topic taxonomy file (`topic_taxonomy.json`) stored in your GCS bucket root. This allows you to customize the hierarchical topic paths used for task classification without redeploying the function.

### Setup

1. Copy the sample taxonomy file to your bucket:

```bash
gsutil cp topic_taxonomy.json gs://your-bucket/topic_taxonomy.json
```

2. Edit the taxonomy to match your needs:

```bash
gsutil cat gs://your-bucket/topic_taxonomy.json | jq . > taxonomy.json
# Edit taxonomy.json locally
gsutil cp taxonomy.json gs://your-bucket/topic_taxonomy.json
```

### Taxonomy Format

```json
{
  "version": "1.0",
  "description": "Your custom taxonomy description",
  "topics": [
    {
      "path": "Work/Projects",
      "description": "Project-specific tasks",
      "examples": ["feature development", "bug fixes"]
    },
    {
      "path": "Personal/Health",
      "description": "Health and wellness tasks",
      "examples": ["doctor appointments", "exercise"]
    }
  ]
}
```

Each topic includes:
- `path`: Hierarchical path (e.g., "Work/Projects", "Personal/Health")
- `description`: What this category is for
- `examples` (optional): Example tasks for this category

### Default Topics

If no taxonomy file is found, these defaults are used:

- `Work/Projects` - Project-specific tasks
- `Work/Meetings` - Meeting action items
- `Work/Admin` - Administrative tasks
- `Work/Finance` - Work-related financial tasks
- `Personal/Health` - Health-related tasks
- `Personal/Finance` - Personal finance
- `Personal/Learning` - Learning and development
- `Personal/Journal` - Personal reflections
- `General` - Uncategorized tasks

### Extending Topics

Gemini can extend topic paths with sub-categories based on context. For example, if your taxonomy includes `Work/Projects`, Gemini may classify a task as `Work/Projects/Alpha` if project "Alpha" is mentioned in the transcript.

## Viewing Extracted Tasks

### Cloud Console

1. Go to [Cloud Storage](https://console.cloud.google.com/storage/browser)
2. Navigate to your bucket → `tasks/` folder
3. Click on any task file to view

### Command Line

```bash
# List recent task files
gsutil ls -l gs://your-bucket/tasks/ | tail -10

# View a specific task file
gsutil cat gs://your-bucket/tasks/2024-01-15_Team_Meeting_abc123.json | jq .
```

## Cost Estimate

- Cloud Function: ~$0.10/month (512MB, runs on new transcripts)
- Vertex AI (Gemini 1.5 Flash): ~$0.000075 per 1K input tokens
- Typical transcript (5K tokens): ~$0.0004 per extraction

**Total: < $1/month for typical usage (assuming ~100 transcripts/month)**

## Limitations

- Maximum transcript size: 15,000 characters sent to Gemini
- Requires Vertex AI API access
- Processing time: 5-15 seconds per transcript
