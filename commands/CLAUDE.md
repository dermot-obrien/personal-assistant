# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is the `commands` directory containing automation tools for personal assistant workflows.

## Projects

### otter-sync

Google Cloud Function that syncs Otter.ai transcripts to Google Cloud Storage.

**Tech stack:** Python 3.12, Google Cloud Functions (2nd gen), Cloud Storage, Secret Manager, Cloud Scheduler

**Key files:**
- `main.py` - Cloud Function entry point with `OtterClient` class and `sync_otter_transcripts` handler
- `deploy.sh` - One-command deployment script
- `local_test.py` - Local testing without deploying

**Commands:**
```bash
# Deploy to Google Cloud
export GCP_PROJECT=your-project-id
./otter-sync/deploy.sh

# Local development
cd otter-sync
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt python-dotenv
python local_test.py

# Run locally
functions-framework --target=sync_otter_transcripts --debug

# View logs
gcloud functions logs read otter-sync --region=us-central1
```

**Architecture:** Cloud Scheduler triggers the function every 30 minutes. The function authenticates with Otter.ai (unofficial API via email/password stored in Secret Manager), fetches new conversations, formats transcripts as Markdown, and uploads to GCS. Processed conversation IDs are tracked in `.processed_ids.json` to avoid duplicates.

### plaud-sync

Google Cloud Function that syncs Plaud Note transcripts to Google Cloud Storage.

**Tech stack:** Python 3.12, Google Cloud Functions (2nd gen), Cloud Storage, Secret Manager, Cloud Scheduler

**Key files:**
- `main.py` - Cloud Function entry point with `PlaudClient` class and `sync_plaud_transcripts` handler
- `deploy.sh` - One-command deployment script
- `get_token.py` - Helper to extract access token from Plaud web app
- `local_test.py` - Local testing and API exploration

**Commands:**
```bash
# Get access token (follow instructions)
python plaud-sync/get_token.py

# Deploy to Google Cloud
export GCP_PROJECT=your-project-id
./plaud-sync/deploy.sh

# Update token in Secret Manager
echo -n 'YOUR_TOKEN' | gcloud secrets versions add plaud-token --data-file=-

# Local development
cd plaud-sync
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt python-dotenv
python local_test.py

# Explore API endpoints
python local_test.py --explore

# Run locally
functions-framework --target=sync_plaud_transcripts --debug

# View logs
gcloud functions logs read plaud-sync --region=us-central1
```

**Architecture:** Cloud Scheduler triggers the function every 30 minutes. The function uses the Plaud web API (unofficial, requires access token from browser session stored in Secret Manager), fetches new recordings, formats transcripts as Markdown with summaries/action items, and uploads to GCS. Processed recording IDs are tracked in `.plaud_processed_ids.json`.

**Note:** Plaud tokens may expire and require periodic renewal from browser.

### task-extractor

Google Cloud Function that listens for new transcripts and extracts tasks using Gemini AI.

**Tech stack:** Python 3.12, Google Cloud Functions (2nd gen), Vertex AI (Gemini 1.5 Flash), Pub/Sub

**Key files:**
- `main.py` - Cloud Function entry point with Gemini integration for task extraction
- `deploy.sh` / `deploy.ps1` - Deployment scripts
- `README.md` - Detailed documentation

**Commands:**
```bash
# Deploy to Google Cloud
export GCP_PROJECT=your-project-id
export GCS_BUCKET=your-bucket-name
./task-extractor/deploy.sh

# View logs
gcloud functions logs read task-extractor --region=us-central1
```

**Architecture:** Triggered by Pub/Sub messages from `otter-sync` when new transcripts are uploaded. Downloads the transcript from GCS, uses Gemini 1.5 Flash to identify tasks/action items, classifies each task with primary and secondary hierarchical topics, and saves results to `tasks/` folder in GCS.

**Output:** Each task includes description, assignee, deadline, priority, primary topic (e.g., "Work/Projects/Alpha"), and secondary topics.

### audio-archive

Google Cloud Function that archives audio files from Otter transcripts to GCS.

**Tech stack:** Python 3.12, Google Cloud Functions (2nd gen), Cloud Storage, Pub/Sub

**Key files:**
- `main.py` - Cloud Function entry point with audio download logic
- `deploy.sh` / `deploy.ps1` - Deployment scripts
- `README.md` - Detailed documentation

**Commands:**
```bash
# Deploy to Google Cloud
export GCP_PROJECT=your-project-id
export GCS_BUCKET=your-bucket-name
./audio-archive/deploy.sh

# View logs
gcloud functions logs read audio-archive --region=us-central1
```

**Architecture:** Triggered by Pub/Sub messages from `otter-sync` when new transcripts are uploaded. Downloads the transcript from GCS, extracts the audio URL, downloads the audio file, and saves it to `audio/` folder with metadata linking to the transcript. Also updates the transcript JSON with the audio file path for bidirectional cross-referencing.

### republish-events

Google Cloud Function that publishes Pub/Sub events for existing transcripts. Used to trigger downstream processing without re-fetching from Otter.ai.

**Tech stack:** Python 3.12, Google Cloud Functions (2nd gen), Cloud Storage, Pub/Sub

**Key files:**
- `main.py` - Cloud Function entry point with transcript listing and event publishing
- `deploy.sh` / `deploy.ps1` - Deployment scripts
- `README.md` - Detailed documentation

**Commands:**
```bash
# Deploy to Google Cloud
export GCP_PROJECT=your-project-id
export GCS_BUCKET=your-bucket-name
./republish-events/deploy.sh

# View logs
gcloud functions logs read republish-events --region=us-central1

# Usage examples (after deployment)
curl "https://REGION-PROJECT.cloudfunctions.net/republish-events?dry_run=true"  # List only
curl "https://REGION-PROJECT.cloudfunctions.net/republish-events"               # Republish all
curl "https://REGION-PROJECT.cloudfunctions.net/republish-events?after=2024-01-01"  # By date
curl "https://REGION-PROJECT.cloudfunctions.net/republish-events?transcript_id=abc123"  # Specific
curl "https://REGION-PROJECT.cloudfunctions.net/republish-events?topic=Personal/Journal"  # By topic
```

**Architecture:** HTTP-triggered function that lists transcripts in GCS, applies optional filters (date, topic, ID), and publishes Pub/Sub events for each. Useful for reprocessing after deploying updates to task-extractor or audio-archive.
