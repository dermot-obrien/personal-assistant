# Handwriting Sync

Google Cloud Function that scans Logseq journal files in a GitHub repository for images of handwritten journal pages, performs OCR using Gemini Vision, and saves transcripts to Google Cloud Storage.

## Features

- **GitHub Integration**: Scans Logseq journal markdown files in your GitHub repository
- **Image Detection**: Extracts image links from markdown (both standard `![](path)` and wiki-style `![[image]]`)
- **Gemini Vision OCR**: Uses Gemini 1.5 Flash for accurate handwriting recognition
- **GCS Storage**: Saves transcripts and original images to a `handwritten/` folder
- **Idempotent**: Tracks processed images in a state file to avoid duplicate processing
- **Flexible Filtering**: Process by date, date range, or limit number of journals

## How It Works

1. Lists journal files from GitHub (e.g., `journals/2024_01_15.md`)
2. Extracts image links from each journal's markdown content
3. Downloads images from GitHub
4. Sends images to Gemini Vision with a handwriting transcription prompt
5. Saves JSON transcript and original image to GCS
6. Updates state file to track processed images

## Prerequisites

- Google Cloud Project with billing enabled
- GitHub repository containing Logseq journal files
- GitHub Personal Access Token with repo read access

## Quick Start

### 1. Set Environment Variables

```bash
# Required
export GCP_PROJECT=your-project-id
export GCS_BUCKET=your-bucket-name
export GITHUB_REPO=owner/repo-name
export GITHUB_TOKEN=ghp_your_token_here

# Optional
export GCP_REGION=us-central1
export GITHUB_BRANCH=main
export LOGSEQ_JOURNAL_PATH=journals
```

### 2. Deploy

```bash
# Linux/macOS
./deploy.sh

# Windows PowerShell
.\deploy.ps1
```

### 3. Test

```bash
# Dry run - list images without processing
curl "https://REGION-PROJECT.cloudfunctions.net/handwriting-sync?dry_run=true"

# Process a specific date
curl "https://REGION-PROJECT.cloudfunctions.net/handwriting-sync?date=2024-01-15"

# Process recent journals
curl "https://REGION-PROJECT.cloudfunctions.net/handwriting-sync?limit=10"
```

## API Reference

### HTTP Endpoint

`GET /` or `POST /`

#### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `date` | string | - | Process only journals from this date (YYYY-MM-DD) |
| `after` | string | - | Process journals after this date |
| `before` | string | - | Process journals before this date |
| `limit` | integer | 50 | Maximum number of journals to process |
| `dry_run` | boolean | false | List images without processing |

#### Response

```json
{
  "status": "success",
  "dry_run": false,
  "journals_processed": 5,
  "images_transcribed": 3,
  "errors": 0,
  "results": [
    {
      "image_path": "assets/journal_page.jpg",
      "status": "success",
      "transcript_path": "handwritten/2024-01-15_journal_page_transcript.json",
      "confidence": "high",
      "word_count": 245
    }
  ],
  "duration_ms": 15234
}
```

## Output Format

### Transcript JSON

```json
{
  "journal_date": "2024-01-15",
  "source_image": "assets/journal_page.jpg",
  "transcribed_at": "2024-01-15T18:30:00+13:00",
  "transcription": "Today I had a wonderful day...",
  "confidence": "high",
  "notes": "Clear handwriting, well-lit image",
  "word_count": 245,
  "has_lists": false,
  "has_drawings": false,
  "language": "English",
  "is_handwritten": true
}
```

### File Structure in GCS

```
gs://your-bucket/
├── handwritten/
│   ├── 2024-01-15_journal_page_transcript.json
│   ├── 2024-01-15_journal_page.jpg
│   ├── 2024-01-14_morning_notes_transcript.json
│   └── 2024-01-14_morning_notes.jpg
└── .handwriting_sync_state.json
```

## Logseq Journal Format

The function expects Logseq-style journal filenames:

```
journals/
├── 2024_01_15.md
├── 2024_01_14.md
└── 2024_01_13.md
```

Images can be linked using:

```markdown
# Standard Markdown
![Journal page](../assets/journal_page.jpg)

# Wiki-style (Logseq/Obsidian)
![[journal_page.jpg]]

# Relative paths
![](./assets/scan.png)
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GCP_PROJECT` | Yes | - | Google Cloud Project ID |
| `GCS_BUCKET` | Yes | - | GCS bucket for storing transcripts |
| `GITHUB_REPO` | Yes | - | GitHub repository (owner/repo) |
| `GITHUB_TOKEN` | Yes | - | GitHub Personal Access Token |
| `GITHUB_BRANCH` | No | main | Git branch to scan |
| `LOGSEQ_JOURNAL_PATH` | No | journals | Path to journal files in repo |
| `LOCAL_TIMEZONE` | No | Pacific/Auckland | Timezone for timestamps |

## Useful Commands

```bash
# View function logs
gcloud functions logs read handwriting-sync --region=us-central1

# List transcribed files
gsutil ls gs://your-bucket/handwritten/

# View a transcript
gsutil cat gs://your-bucket/handwritten/2024-01-15_journal_page_transcript.json

# Check state file
gsutil cat gs://your-bucket/.handwriting_sync_state.json

# Clear state to force reprocessing
gsutil rm gs://your-bucket/.handwriting_sync_state.json
```

## Optional: Cloud Scheduler

Set up automatic daily processing:

```bash
gcloud scheduler jobs create http handwriting-sync-daily \
    --location=us-central1 \
    --schedule='0 6 * * *' \
    --uri='https://FUNCTION_URL?limit=20' \
    --http-method=GET \
    --oidc-service-account-email=handwriting-sync-sa@PROJECT.iam.gserviceaccount.com
```

## Cost Considerations

- **Gemini Vision API**: ~$0.00025 per image (varies by image size)
- **Cloud Functions**: Gen2, ~$0.40/million invocations + compute time
- **Cloud Storage**: Standard storage rates apply

## Troubleshooting

### Image Not Found

- Check the image path in your markdown
- Verify the image exists in the GitHub repository
- Check GitHub token has read access to the repository

### OCR Quality Issues

- Ensure images are well-lit and in focus
- Higher resolution images generally produce better results
- Check the `confidence` field in transcript results

### Authentication Errors

- Verify `GITHUB_TOKEN` is valid and has repo access
- Check service account has necessary IAM permissions

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   GitHub    │────▶│  Handwriting │────▶│    GCS      │
│  (Logseq)   │     │    Sync      │     │ (Transcripts│
└─────────────┘     └──────┬───────┘     └─────────────┘
                          │
                          ▼
                   ┌──────────────┐
                   │   Gemini     │
                   │   Vision     │
                   └──────────────┘
```
