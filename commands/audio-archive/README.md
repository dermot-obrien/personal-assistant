# Audio Archive

A Google Cloud Function that listens for new Otter transcripts and automatically downloads and archives the audio files.

## Architecture

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   otter-sync    │─────▶│    Pub/Sub      │─────▶│  audio-archive  │
│  (transcripts)  │      │    (events)     │      │   (downloads)   │
└─────────────────┘      └─────────────────┘      └────────┬────────┘
                                                           │
                                                           ▼
                                                  ┌─────────────────┐
                                                  │  Cloud Storage  │
                                                  │    (audio/)     │
                                                  └─────────────────┘
```

## How It Works

1. **Trigger**: Receives Pub/Sub messages from `otter-sync` when new transcripts are uploaded
2. **Fetch Transcript**: Downloads the transcript JSON from Cloud Storage
3. **Extract Audio URL**: Looks for `audio_url` or `download_url` fields in the transcript
4. **Download Audio**: Downloads the audio file from Otter.ai
5. **Archive**: Saves the audio to the `audio/` folder with matching metadata
6. **Cross-Reference**: Updates the transcript JSON with the audio file path

## File Naming Convention

Audio files are saved with names matching their transcript counterparts:

```
audio/2024-01-15_10-30_Team_Meeting_abc123.mp3
transcripts/2024-01-15_10-30_Team_Meeting_abc123.json
```

## Metadata

Each audio file includes GCS metadata for easy cross-referencing:

| Metadata Key | Description |
|-------------|-------------|
| `transcript_id` | Otter.ai conversation ID |
| `transcript_title` | Original conversation title |
| `transcript_topic` | Hierarchical topic path |
| `transcript_blob_path` | Path to corresponding transcript JSON |
| `transcript_created_at` | When the conversation was created |
| `archived_at` | When the audio was archived |
| `audio_size_bytes` | Size of the audio file |

The transcript JSON is also updated with:
- `audio_archive_path`: Path to the archived audio file
- `audio_archived_at`: When the audio was archived

## Prerequisites

- Google Cloud project with billing enabled
- `otter-sync` function already deployed with Pub/Sub events enabled
- `task-extractor` (optional) listens to the same events

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
cd audio-archive
chmod +x deploy.sh
./deploy.sh
```

**Windows PowerShell:**
```powershell
cd audio-archive
.\deploy.ps1
```

### 3. Test

Upload a new transcript via `otter-sync`, then check the logs:

```bash
gcloud functions logs read audio-archive --region=$GCP_REGION --limit=20
```

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `GCS_BUCKET` | GCS bucket for audio files | Required |
| `LOCAL_TIMEZONE` | Timezone for timestamps | `Pacific/Auckland` |

## Viewing Archived Audio

### Cloud Console

1. Go to [Cloud Storage](https://console.cloud.google.com/storage/browser)
2. Navigate to your bucket → `audio/` folder
3. Click on any audio file to view metadata or download

### Command Line

```bash
# List recent audio files
gsutil ls -l gs://your-bucket/audio/ | tail -10

# View metadata for an audio file
gsutil stat gs://your-bucket/audio/2024-01-15_Team_Meeting_abc123.mp3

# Download an audio file
gsutil cp gs://your-bucket/audio/2024-01-15_Team_Meeting_abc123.mp3 ./
```

## Cost Estimate

- Cloud Function: ~$0.20/month (1GB memory, runs on new transcripts)
- Storage: ~$0.02/GB/month for audio files
- Egress: $0.12/GB for downloads from outside GCP

**Example: 100 transcripts/month, average 10MB audio each:**
- Function: ~$0.20
- Storage: ~$0.02 (1GB)
- **Total: < $1/month**

## Limitations

- Maximum audio file size: Limited by Cloud Function memory and timeout (9 minutes)
- Requires audio URL to be present in transcript data
- Audio URLs may expire; archiving happens immediately on transcript upload
