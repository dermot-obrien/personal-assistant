# Plaud Note to Google Cloud Storage Sync

A Google Cloud Function that monitors Plaud Note for new recordings and automatically copies transcripts to Google Cloud Storage.

## Architecture

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│ Cloud Scheduler │─────▶│ Cloud Function  │─────▶│  Cloud Storage  │
│  (every 30min)  │      │  (plaud-sync)   │      │   (transcripts) │
└─────────────────┘      └────────┬────────┘      └─────────────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ Secret Manager  │
                         │ (access token)  │
                         └─────────────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │  Plaud Web API  │
                         │  (unofficial)   │
                         └─────────────────┘
```

## Prerequisites

- Google Cloud project with billing enabled
- `gcloud` CLI installed and authenticated
- Plaud Note account with recordings synced to cloud
- Access token from Plaud web app

## Important Note

Plaud does not yet have an official API for accessing your recordings. The [official Developer Platform](https://www.plaud.ai/pages/developer-platform) is for building integrations with Plaud devices, not for accessing your personal data.

This solution uses the internal web API that powers [web.plaud.ai](https://web.plaud.ai/). It requires a session token extracted from your browser, which may expire and need periodic renewal.

## Deployment

### 1. Get Your Access Token

```bash
python get_token.py
```

Follow the instructions to extract your token from the Plaud web app.

### 2. Set Configuration

```bash
export GCP_PROJECT=your-project-id
export GCP_REGION=us-central1
export GCS_BUCKET=plaud-transcripts
```

### 3. Deploy

```bash
chmod +x deploy.sh
./deploy.sh
```

### 4. Add Your Token

```bash
echo -n 'your-access-token' | gcloud secrets versions add plaud-token --data-file=-
```

### 5. Test

```bash
gcloud functions call plaud-sync --region=$GCP_REGION
```

## Local Development

1. Create virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   pip install python-dotenv
   ```

2. Copy environment template:
   ```bash
   cp .env.example .env
   # Edit .env with your token
   ```

3. Run local test:
   ```bash
   python local_test.py
   ```

4. Explore API endpoints:
   ```bash
   python local_test.py --explore
   ```

5. Run function locally:
   ```bash
   functions-framework --target=sync_plaud_transcripts --debug
   # Then visit http://localhost:8080
   ```

## Output Structure

Transcripts are saved to GCS with the following structure:

```
gs://your-bucket/
├── .plaud_processed_ids.json      # Tracks synced recordings
└── plaud-transcripts/
    ├── 2024-01-15_Team_Meeting_abc123.md
    ├── 2024-01-16_Client_Call_def456.md
    └── ...
```

Each transcript file is formatted as Markdown with:
- Title, date, and duration
- AI summary and action items (if available)
- Full transcript with speaker names and timestamps

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `GCP_PROJECT` | Google Cloud project ID | Required |
| `GCS_BUCKET` | Target GCS bucket name | Required |
| `PLAUD_TOKEN_SECRET` | Secret Manager ID for access token | `plaud-token` |

## Token Renewal

The Plaud access token may expire. If you see authentication errors:

1. Login to [web.plaud.ai](https://web.plaud.ai/)
2. Extract the new token (see `get_token.py`)
3. Update the secret:
   ```bash
   echo -n 'NEW_TOKEN' | gcloud secrets versions add plaud-token --data-file=-
   ```

Consider setting up monitoring/alerts for authentication failures.

## Limitations

- Uses unofficial Plaud web API (may break if Plaud changes their API)
- Requires manual token extraction (no OAuth flow)
- Token may expire and need periodic renewal
- API endpoints are discovered/guessed and may not match exactly

## Monitoring

View function logs:
```bash
gcloud functions logs read plaud-sync --region=$GCP_REGION --limit=50
```

## Cost Estimate

- Cloud Function: ~$0.40/month (256MB, 300s timeout, runs 48x/day)
- Cloud Scheduler: Free tier (up to 3 jobs)
- Cloud Storage: ~$0.02/GB/month
- Secret Manager: Free tier (up to 10,000 accesses/month)

**Total: < $1/month for typical usage**

## Resources

- [Plaud Web App](https://web.plaud.ai/)
- [Plaud Developer Platform](https://www.plaud.ai/pages/developer-platform) (for device integrations)
- [Plaud SDK on GitHub](https://github.com/Plaud-AI/plaud-sdk)
- [Community Exporter (Chrome Extension)](https://github.com/josephhyatt/plaud-exporter)
