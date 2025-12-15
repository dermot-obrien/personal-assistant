# Republish Events

A Google Cloud Function that publishes Pub/Sub events for existing transcripts in GCS. Used to trigger downstream processing (task-extractor, audio-archive) without re-fetching transcripts from Otter.ai.

## Use Cases

- **Reprocess all transcripts** after deploying a new version of task-extractor
- **Backfill audio files** for transcripts that existed before audio-archive was deployed
- **Rerun task extraction** with an updated topic taxonomy
- **Process specific transcripts** by ID or date range

## Architecture

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│  republish-     │─────▶│    Pub/Sub      │─────▶│ task-extractor  │
│    events       │      │    (events)     │      │ audio-archive   │
└────────┬────────┘      └─────────────────┘      └─────────────────┘
         │
         ▼
┌─────────────────┐
│  Cloud Storage  │
│  (transcripts/) │
└─────────────────┘
```

## How It Works

1. **List**: Scans the `transcripts/` folder in GCS
2. **Filter**: Applies optional filters (date range, topic, transcript ID)
3. **Read**: Downloads each transcript JSON to extract metadata
4. **Publish**: Sends a Pub/Sub event with `event_type: transcript.republished`

## Query Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `after` | Only process transcripts after this date | `?after=2024-01-01` |
| `before` | Only process transcripts before this date | `?before=2024-12-31` |
| `topic` | Filter by topic (substring match) | `?topic=Personal/Journal` |
| `limit` | Maximum number to process | `?limit=10` |
| `transcript_id` | Process only this transcript | `?transcript_id=abc123` |
| `dry_run` | List transcripts without publishing | `?dry_run=true` |

## Prerequisites

- Google Cloud project with billing enabled
- `otter-sync` function already deployed with transcripts in GCS
- Pub/Sub topic `otter-transcript-events` exists

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
cd republish-events
chmod +x deploy.sh
./deploy.sh
```

**Windows PowerShell:**
```powershell
cd republish-events
.\deploy.ps1
```

## Usage Examples

The function requires authentication. Use `gcloud` to get an identity token:

### Dry Run (List Only)

```bash
# List all transcripts without publishing
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://REGION-PROJECT.cloudfunctions.net/republish-events?dry_run=true"
```

### Republish All Transcripts

```bash
# Trigger full reprocessing
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://REGION-PROJECT.cloudfunctions.net/republish-events"
```

### Republish Recent Transcripts

```bash
# Last 7 days
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://REGION-PROJECT.cloudfunctions.net/republish-events?after=$(date -d '7 days ago' +%Y-%m-%d)"

# Specific date range
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://REGION-PROJECT.cloudfunctions.net/republish-events?after=2024-01-01&before=2024-01-31"
```

### Republish Specific Transcript

```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://REGION-PROJECT.cloudfunctions.net/republish-events?transcript_id=abc123"
```

### Republish by Topic

```bash
# All journal entries
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://REGION-PROJECT.cloudfunctions.net/republish-events?topic=Personal/Journal"

# All work-related
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://REGION-PROJECT.cloudfunctions.net/republish-events?topic=Work"
```

### PowerShell Examples

```powershell
# Get auth token
$token = gcloud auth print-identity-token
$headers = @{ Authorization = "Bearer $token" }

# Dry run
Invoke-RestMethod -Headers $headers "https://REGION-PROJECT.cloudfunctions.net/republish-events?dry_run=true"

# Republish last 7 days
$weekAgo = (Get-Date).AddDays(-7).ToString("yyyy-MM-dd")
Invoke-RestMethod -Headers $headers "https://REGION-PROJECT.cloudfunctions.net/republish-events?after=$weekAgo"
```

## Response Format

```json
{
  "status": "success",
  "dry_run": false,
  "total_transcripts": 150,
  "processed": 25,
  "skipped": 0,
  "errors": 0,
  "duration_ms": 3500,
  "published": [
    {
      "path": "transcripts/2024-01-15_10-30_Team_Meeting_abc123.json",
      "otter_id": "abc123",
      "title": "Team Meeting"
    }
  ]
}
```

## Event Format

Published events have the same format as otter-sync events, with `event_type: transcript.republished`:

```json
{
  "event_type": "transcript.republished",
  "otter_id": "abc123",
  "title": "Team Meeting",
  "topic": "Work/Meetings/Internal",
  "gcs_path": "gs://bucket/transcripts/2024-01-15_Team_Meeting_abc123.json",
  "gcs_bucket": "bucket",
  "gcs_blob": "transcripts/2024-01-15_Team_Meeting_abc123.json",
  "created_at": "2024-01-15T10:30:00+13:00",
  "synced_at": "2024-01-15T11:00:00+13:00",
  "republished_at": "2024-01-20T14:30:00+13:00"
}
```

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `GCP_PROJECT` | Google Cloud project ID | Required |
| `GCS_BUCKET` | GCS bucket containing transcripts | Required |
| `PUBSUB_TOPIC` | Pub/Sub topic for events | Required |
| `LOCAL_TIMEZONE` | Timezone for timestamps | `Pacific/Auckland` |

## Cost Estimate

- Cloud Function: ~$0.01 per invocation (256MB, short-lived)
- Pub/Sub: $0.40 per million messages
- Storage reads: $0.004 per 10,000 reads

**Example: Republishing 100 transcripts costs < $0.01**

## Authentication

The function requires IAM authentication. Users must have the `roles/cloudfunctions.invoker` role to call it. Use `gcloud auth print-identity-token` to get an identity token for requests.
