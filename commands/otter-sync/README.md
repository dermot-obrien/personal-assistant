# Otter.ai to Google Cloud Storage Sync

A Google Cloud Function that monitors Otter.ai for new conversations and automatically copies transcripts to Google Cloud Storage.

## Architecture

```
                              ┌─────────────────┐
                              │   Pub/Sub       │
                              │ (start-cycle)   │
                              └────────┬────────┘
                                       │
┌─────────────────┐      ┌─────────────▼───────────┐      ┌─────────────────┐
│ Cloud Scheduler │────▶│    Cloud Functions      │─────▶│  Cloud Storage  │
│  (every 30min)  │      │                         │      │   (transcripts) │
└─────────────────┘      │  otter-sync (HTTP)      │      └────────┬────────┘
                         │  otter-sync-pubsub      │               │
                         └─────────────┬───────────┘               ▼
                                       │                  ┌─────────────────┐
                                       │                  │     Pub/Sub     │
                                       │                  │ (transcript     │
                                       │                  │     events)     │
                                       ▼                  └────────┬────────┘
                              ┌─────────────────┐                  │
                              │ Secret Manager  │                  ▼
                              │ (credentials)   │         ┌─────────────────┐
                              └────────┬────────┘         │   Subscribers   │
                                       │                  │  (your apps)    │
                                       ▼                  └─────────────────┘
                              ┌─────────────────┐
                              │   Otter.ai API  │
                              │  (unofficial)   │
                              └─────────────────┘
```

## Features

- **Dual Trigger Support**: Can be triggered via HTTP (Cloud Scheduler) or Pub/Sub (`start-cycle` topic)
- **Automatic Sync**: Monitors Otter.ai and syncs new transcripts to GCS
- **Event-Driven**: Publishes events to Pub/Sub when new transcripts are uploaded
- **Topic Mapping**: Maps Otter folders to hierarchical topic paths
- **Observability**: Full OpenTelemetry tracing and structured logging

---

## Quick Start

### Prerequisites

- Google Cloud account with billing enabled
- `gcloud` CLI installed and authenticated
- Otter.ai account

### 1. Set Configuration

```bash
export GCP_PROJECT="your-project-id"
export GCP_REGION="us-central1"
export GCS_BUCKET="otter-transcripts-yourname"
```

### 2. Deploy

```bash
chmod +x deploy.sh
./deploy.sh
```

### 3. Add Your Credentials

```bash
echo -n 'your-email@example.com' | gcloud secrets versions add otter-email --data-file=-
echo -n 'your-password' | gcloud secrets versions add otter-password --data-file=-
```

### 4. Test

```bash
# Test HTTP trigger
gcloud functions call otter-sync --region=$GCP_REGION

# Test Pub/Sub trigger
gcloud pubsub topics publish start-cycle --message='{}'
```

---

## Detailed Setup Guide

### Step 1: Create a Google Cloud Account

1. Go to [cloud.google.com](https://cloud.google.com)
2. Click **Get started for free**
3. Sign in with your Google account
4. Complete the registration (requires credit card, but you get $300 free credits)
5. Accept the terms of service

### Step 2: Create a New Project

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Click the project dropdown at the top of the page
3. Click **New Project**
4. Enter a project name (e.g., `otter-sync-project`)
5. Click **Create**
6. Wait for the project to be created, then select it

**Note your Project ID** - you'll need it later.

### Step 3: Install Google Cloud CLI

#### Windows

Download the installer from [cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install)

#### macOS

```bash
brew install google-cloud-sdk
```

#### Linux

```bash
curl https://sdk.cloud.google.com | bash
exec -l $SHELL
```

### Step 4: Authenticate with Google Cloud

```bash
# Login to Google Cloud (opens browser)
gcloud auth login

# Set your project
gcloud config set project YOUR_PROJECT_ID

# Set up application default credentials (required for local development)
gcloud auth application-default login
```

This authenticates:
- `gcloud auth login` - Authenticates the gcloud CLI for running commands
- `gcloud auth application-default login` - Sets up credentials for local development and testing

### Step 5: Enable Billing

1. Go to [Billing](https://console.cloud.google.com/billing) in Google Cloud Console
2. Link a billing account to your project

### Step 6: Set Environment Variables

#### Windows (PowerShell)

```powershell
$env:GCP_PROJECT = "your-project-id"
$env:GCP_REGION = "us-central1"
$env:GCS_BUCKET = "your-unique-bucket-name"
```

#### macOS/Linux

```bash
export GCP_PROJECT="your-project-id"
export GCP_REGION="us-central1"
export GCS_BUCKET="your-unique-bucket-name"
```

**Important:** The bucket name must be globally unique across all of Google Cloud.

### Step 7: Deploy

#### macOS/Linux

```bash
cd /path/to/commands/otter-sync
chmod +x deploy.sh
./deploy.sh
```

#### Windows (PowerShell)

```powershell
cd C:\path\to\commands\otter-sync
.\deploy.ps1
```

The deployment takes 2-3 minutes and deploys:
- `otter-sync` - HTTP-triggered function (for Cloud Scheduler)
- `otter-sync-pubsub` - Pub/Sub-triggered function (for `start-cycle` events)

### Step 8: Add Your Otter.ai Credentials

```bash
echo -n 'your-otter-email@example.com' | gcloud secrets versions add otter-email --data-file=-
echo -n 'your-otter-password' | gcloud secrets versions add otter-password --data-file=-
```

### Step 9: Test the Function

```bash
# Test HTTP trigger
gcloud functions call otter-sync --region=$GCP_REGION

# Test Pub/Sub trigger
gcloud pubsub topics publish start-cycle --message='{}'

# Test with custom page size
gcloud pubsub topics publish start-cycle --message='{"page_size": 100}'
```

### Step 10: Verify Transcripts

1. Go to [Cloud Storage](https://console.cloud.google.com/storage/browser) in the console
2. Click on your bucket
3. Navigate to the `transcripts/` folder

---

## Trigger Options

### HTTP Trigger (Cloud Scheduler)

The `otter-sync` function is triggered by Cloud Scheduler every 30 minutes by default.

```bash
# Manually trigger
gcloud functions call otter-sync --region=$GCP_REGION

# Change schedule
gcloud scheduler jobs update http otter-sync-scheduler \
    --location=$GCP_REGION \
    --schedule="0 * * * *"  # Every hour
```

### Pub/Sub Trigger (start-cycle)

The `otter-sync-pubsub` function listens to the `start-cycle` Pub/Sub topic, allowing external systems to trigger syncs.

```bash
# Trigger a sync
gcloud pubsub topics publish start-cycle --message='{}'

# Trigger with custom page size
gcloud pubsub topics publish start-cycle --message='{"page_size": 100}'

# Force re-process the latest conversation (useful for testing)
gcloud pubsub topics publish start-cycle --message='{"force_latest": true}'
```

**Message payload options:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `page_size` | int | 50 | Number of speeches to fetch from Otter |
| `force_latest` | bool | false | Re-process the most recent conversation even if already synced. Useful for testing transcript formatting changes |

---

## Output Structure

Transcripts are saved to GCS as JSON:

```
gs://your-bucket/
├── .processed_ids.json              # Tracks synced conversations
├── otter_topic_mapping.json         # Folder to topic mapping
└── transcripts/
    ├── 2024-01-15_10-30_Team_Meeting_abc123.json
    ├── 2024-01-16_14-00_Client_Call_def456.json
    └── ...
```

Each transcript JSON includes:
- Title, summary, and speech outline
- Full transcript with speaker names and timestamps
- Topic/folder classification
- Metadata (duration, language, speakers, etc.)

---

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `GCP_PROJECT` | Google Cloud project ID | Required |
| `GCS_BUCKET` | Target GCS bucket name | Required |
| `OTTER_EMAIL_SECRET` | Secret Manager ID for email | `otter-email` |
| `OTTER_PASSWORD_SECRET` | Secret Manager ID for password | `otter-password` |
| `PUBSUB_TOPIC` | Pub/Sub topic for transcript events | `otter-transcript-events` |
| `LOCAL_TIMEZONE` | Timezone for timestamps | `Pacific/Auckland` |

---

## Pub/Sub Event System

### Transcript Events

When a new transcript is uploaded, a Pub/Sub message is published:

```json
{
  "event_type": "transcript.created",
  "otter_id": "abc123",
  "title": "Team Meeting",
  "topic": "Work/Meetings",
  "gcs_path": "gs://bucket/transcripts/2024-01-15_10-30_Team_Meeting_abc123.json",
  "gcs_bucket": "otter-transcripts",
  "gcs_blob": "transcripts/2024-01-15_10-30_Team_Meeting_abc123.json",
  "created_at": "2024-01-15T10:30:00+13:00",
  "synced_at": "2024-01-15T11:00:00+13:00"
}
```

### Creating Subscribers

**Pull Subscription:**
```bash
gcloud pubsub subscriptions create my-subscriber --topic=otter-transcript-events
gcloud pubsub subscriptions pull my-subscriber --auto-ack
```

**Push Subscription (webhook):**
```bash
gcloud pubsub subscriptions create my-webhook \
    --topic=otter-transcript-events \
    --push-endpoint=https://your-service.com/webhook
```

**Cloud Function Trigger:**
```bash
gcloud functions deploy my-handler \
    --gen2 \
    --region=$GCP_REGION \
    --runtime=python312 \
    --trigger-topic=otter-transcript-events \
    --entry-point=handle_transcript
```

### Example Subscriber (Python)

```python
import base64
import json
import functions_framework
from google.cloud import storage

@functions_framework.cloud_event
def handle_transcript(cloud_event):
    """Process new transcript events."""
    message_data = cloud_event.data["message"]["data"]
    data = json.loads(base64.b64decode(message_data))

    print(f"New transcript: {data['title']}")
    print(f"Topic: {data['topic']}")
    print(f"GCS Path: {data['gcs_path']}")

    # Read the transcript content
    storage_client = storage.Client()
    bucket = storage_client.bucket(data['gcs_bucket'])
    blob = bucket.blob(data['gcs_blob'])
    content = json.loads(blob.download_as_text())

    # Process the transcript...
    print(f"Full text length: {len(content.get('full_text', ''))}")
```

---

## Local Development

1. Create virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   pip install python-dotenv pytest
   ```

2. Copy environment template:
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. Run local test:
   ```bash
   python local_test.py
   ```

4. Run function locally:
   ```bash
   functions-framework --target=sync_otter_transcripts --debug
   # Then visit http://localhost:8080
   ```

---

## Testing

The project includes comprehensive unit tests that validate transcript formatting, JSON output, and error handling.

### Running Unit Tests

```bash
# Run all unit tests (excludes live API tests)
pytest test_otter_sync.py -v

# Run specific test class
pytest test_otter_sync.py -v -k "TestOtterClientSanitization"

# Run with coverage
pytest test_otter_sync.py -v --cov=main
```

### Test Categories

| Test Class | Description |
|------------|-------------|
| `TestOtterClientSanitization` | Text sanitization (control chars, unicode) |
| `TestOtterClientOutlineParsing` | Speech outline parsing (JSON, Python-style strings) |
| `TestOtterClientFormatTranscript` | Transcript formatting and structure |
| `TestTopicMapping` | Folder-to-topic resolution |
| `TestJsonValidation` | JSON output validation |
| `TestLocalGCSOutput` | Mock GCS upload to local folder |
| `TestProcessedIds` | Processed IDs tracking |
| `TestIntegration` | Full sync workflow simulation |
| `TestEdgeCases` | Edge cases (empty data, missing fields, long titles) |

### Test Output

Unit tests write output to `test_output/` for inspection:
- `test_output/transcripts/` - Formatted transcript samples
- `test_output/gcs/transcripts/` - Simulated GCS uploads
- `test_output/edge_cases/` - Edge case outputs

### Live API Tests

Live tests connect to the real Otter API and download transcripts. **Disabled by default.**

```bash
# Run live tests (requires OTTER_EMAIL and OTTER_PASSWORD in .env)
pytest test_otter_sync.py -v -m live_otter

# Fetch only the latest transcript (quick test)
pytest test_otter_sync.py -v -m live_otter -k "test_fetch_latest"

# Fetch ALL transcripts and save locally
pytest test_otter_sync.py -v -m live_otter -k "test_fetch_all"

# Test a specific conversation by ID (useful for debugging failures)
OTTER_TEST_SPEECH_ID=abc123 pytest test_otter_sync.py -v -m live_otter -k "test_fetch_specific"
```

**Live test output:**
- `test_output/live_otter/transcripts/` - All formatted transcripts as JSON
- `test_output/live_otter/raw/` - Raw API responses from Otter (useful for debugging)
- `test_output/live_otter/sync_report.json` - Summary with success/error counts
- `test_output/live_otter/failed_conversations.json` - Detailed error info for failed conversations (ID, title, error, traceback)
- `test_output/live_otter/latest/` - Latest transcript + raw API response
- `test_output/live_otter/specific/` - Specific conversation test output (raw + formatted)

**Note:** Live tests are robust - individual conversation failures are logged but don't fail the entire test. The test only fails if ALL conversations fail to process.

---

## Observability

### Distributed Tracing

Traces are exported to [Cloud Trace](https://console.cloud.google.com/traces) using native OTLP export.

**Trace spans include:**
- `sync_otter_transcripts` / `start_cycle_pubsub` - Root span
- `get_secrets` - Secret retrieval
- `otter_authenticate` - Otter.ai authentication
- `fetch_speeches` - Retrieving speech list
- `process_transcript` - Processing individual transcripts
- `upload_to_gcs` - Uploading to Cloud Storage
- `publish_event` - Publishing Pub/Sub events

### Viewing Logs

```bash
# View recent logs
gcloud functions logs read otter-sync --region=$GCP_REGION --limit=50

# View Pub/Sub triggered function logs
gcloud functions logs read otter-sync-pubsub --region=$GCP_REGION --limit=50

# Filter by event type
gcloud logging read "jsonPayload.event=sync_completed" --limit=10
```

### Log Events

| Event | Severity | Description |
|-------|----------|-------------|
| `sync_started` | INFO | Sync process initiated |
| `start_cycle_triggered` | INFO | Pub/Sub trigger received |
| `auth_success` | INFO | Authenticated with Otter.ai |
| `speeches_fetched` | INFO | Retrieved speech list |
| `transcript_uploaded` | INFO | New transcript saved to GCS |
| `sync_completed` | INFO | Sync finished successfully |
| `speech_error` | WARNING | Failed to process individual speech |
| `sync_failed` | ERROR | Sync process failed |

---

## Troubleshooting

### Common Issues

**"Permission denied" errors:**
```bash
gcloud projects add-iam-policy-binding $GCP_PROJECT \
    --member="serviceAccount:otter-sync-sa@$GCP_PROJECT.iam.gserviceaccount.com" \
    --role="roles/storage.objectAdmin"
```

**"Secret not found" errors:**
```bash
gcloud secrets list
gcloud secrets versions list otter-email
```

**Authentication failed with Otter.ai:**
- Verify your email/password are correct
- Check if Otter.ai requires 2FA (not supported)
- Try logging into otter.ai manually

**Function times out:**
```bash
gcloud functions deploy otter-sync --region=$GCP_REGION --timeout=540s
```

---

## Cost Estimate

| Service | Estimated Cost |
|---------|---------------|
| Cloud Functions | ~$0.40/month |
| Cloud Scheduler | Free (up to 3 jobs) |
| Cloud Storage | ~$0.02/GB/month |
| Secret Manager | Free (up to 10K accesses) |
| Pub/Sub | Free (up to 10GB/month) |
| Cloud Trace | Free (first 2.5M spans/month) |

**Total: < $1/month for typical usage**

---

## Cleanup

To remove all resources:

```bash
# Delete functions
gcloud functions delete otter-sync --region=$GCP_REGION
gcloud functions delete otter-sync-pubsub --region=$GCP_REGION

# Delete scheduler
gcloud scheduler jobs delete otter-sync-scheduler --location=$GCP_REGION

# Delete bucket (and all contents)
gsutil rm -r gs://$GCS_BUCKET

# Delete secrets
gcloud secrets delete otter-email
gcloud secrets delete otter-password

# Delete Pub/Sub topics
gcloud pubsub topics delete otter-transcript-events
gcloud pubsub topics delete start-cycle

# Delete service account
gcloud iam service-accounts delete otter-sync-sa@$GCP_PROJECT.iam.gserviceaccount.com
```

---

## Limitations

- Uses unofficial Otter.ai API (may break if Otter changes their API)
- Requires email/password authentication (no OAuth)
- Rate limits may apply for frequent polling
- 2FA not supported
