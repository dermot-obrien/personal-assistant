# Logseq Sync

A Google Cloud Function that syncs transcripts and extracted tasks to Logseq journal files stored in GitHub.

## Overview

This function listens to the same Pub/Sub topic as task-extractor. When a transcript event arrives, it:

1. Downloads the transcript from GCS
2. Finds associated tasks (from task-extractor output)
3. Formats them as Logseq blocks with properties
4. Updates the daily journal file in your GitHub repository

## Architecture

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│   otter-sync    │─────▶│    Pub/Sub      │─────▶│  logseq-sync    │
│ (transcripts)   │      │    (events)     │      │                 │
└─────────────────┘      └────────┬────────┘      └────────┬────────┘
                                  │                        │
                                  ▼                        ▼
                         ┌─────────────────┐      ┌─────────────────┐
                         │ task-extractor  │      │     GitHub      │
                         │    (tasks)      │      │ (Logseq repo)   │
                         └─────────────────┘      └─────────────────┘
```

## Output Format

Each transcript creates a Logseq block with properties:

```markdown
- ## 10:30 Team Meeting
  otter-id:: abc123
  collapsed:: true
  topic:: [[Work/Meetings/Internal]]
  - **Summary**: Discussed project timeline and next steps.
  - ### Tasks
    - TODO Review the budget proposal
      priority:: high
      topic:: [[Work/Finance/Budget]]
      assignee:: John
      deadline:: Friday
    - TODO Schedule follow-up meeting
      priority:: medium
      topic:: [[Work/Meetings/Planning]]
```

## Prerequisites

- Google Cloud project with billing enabled
- `otter-sync` and `task-extractor` functions deployed
- GitHub repository for Logseq notes
- GitHub personal access token with repo access

## GitHub Token Setup

1. Go to [GitHub Settings > Developer Settings > Personal Access Tokens](https://github.com/settings/tokens)
2. Click "Generate new token (classic)"
3. Select scopes:
   - `repo` (for private repositories)
   - OR `public_repo` (for public repositories only)
4. Copy the token (starts with `ghp_`)

## Deployment

### 1. Set Environment Variables

```bash
export GCP_PROJECT=your-project-id
export GCP_REGION=us-central1
export GCS_BUCKET=your-bucket-name
export LOGSEQ_GITHUB_REPO=owner/logseq-notes
export LOGSEQ_GITHUB_TOKEN=ghp_xxxxxxxxxxxx
export LOGSEQ_GITHUB_BRANCH=main           # optional, defaults to 'main'
export LOGSEQ_JOURNAL_PATH=journals        # optional, defaults to 'journals'
```

### 2. Deploy

**macOS/Linux:**
```bash
cd logseq-sync
chmod +x deploy.sh
./deploy.sh
```

**Windows PowerShell:**
```powershell
cd logseq-sync
.\deploy.ps1
```

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `GCP_PROJECT` | Google Cloud project ID | Required |
| `GCS_BUCKET` | GCS bucket with transcripts/tasks | Required |
| `GITHUB_REPO` | GitHub repo in `owner/repo` format | Required |
| `GITHUB_TOKEN` | GitHub personal access token | Required (stored in Secret Manager) |
| `GITHUB_BRANCH` | Branch to update | `main` |
| `LOGSEQ_JOURNAL_PATH` | Path to journals folder | `journals` |
| `LOCAL_TIMEZONE` | Timezone for dates | `Pacific/Auckland` |

## Journal File Naming

Journal files follow Logseq's default naming convention:
- `journals/YYYY_MM_DD.md`

The date is based on the transcript's `created_at` timestamp, converted to local timezone.

## State Management

The function tracks synced transcripts in `.logseq_sync_state.json`:

```json
{
  "abc123": "2024_01_15",
  "def456": "2024_01_16"
}
```

This prevents duplicate entries when events are republished.

## Usage Examples

### View Logs

```bash
gcloud functions logs read logseq-sync --region=us-central1
```

### Check Sync State

```bash
gsutil cat gs://your-bucket/.logseq_sync_state.json | jq .
```

### Force Re-sync

Clear the state file and use republish-events:

```bash
# Clear state
gsutil rm gs://your-bucket/.logseq_sync_state.json

# Republish all transcripts
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://REGION-PROJECT.cloudfunctions.net/republish-events"
```

### Re-sync Specific Transcript

```bash
gsutil cat gs://your-bucket/.logseq_sync_state.json | \
  jq 'del(.["transcript_id"])' | \
  gsutil cp - gs://your-bucket/.logseq_sync_state.json

curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "https://REGION-PROJECT.cloudfunctions.net/republish-events?transcript_id=abc123"
```

### Update GitHub Token

```bash
# Add new version of the secret
echo -n 'ghp_new_token' | gcloud secrets versions add logseq-github-token --data-file=-

# Verify
gcloud secrets versions list logseq-github-token
```

## Logseq Properties

The function uses Logseq properties for metadata:

| Property | Description |
|----------|-------------|
| `otter-id` | Unique transcript identifier |
| `collapsed` | Keeps blocks collapsed by default |
| `topic` | Links to topic page (e.g., `[[Work/Meetings]]`) |
| `priority` | Task priority (high/medium/low) |
| `assignee` | Person responsible for the task |
| `deadline` | Due date if mentioned |

## Troubleshooting

### "Failed to update GitHub file"

- Check that the token has correct permissions
- Verify the repository exists and is accessible
- Check if branch protection rules are blocking

### "Already synced" messages

The transcript was previously synced. Clear state to force re-sync:
```bash
gsutil rm gs://your-bucket/.logseq_sync_state.json
```

### No tasks appearing

- Verify task-extractor is running and producing output
- Check that tasks are in `gs://bucket/tasks/` folder
- Look for matching transcript ID in task filenames

## Cost Estimate

- Cloud Function: ~$0.001 per invocation (256MB, short-lived)
- Secret Manager: $0.03 per 10,000 access operations
- GitHub API: Free within rate limits

**Total: < $0.50/month for typical usage**
