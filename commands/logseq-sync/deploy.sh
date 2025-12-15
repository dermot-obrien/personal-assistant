#!/bin/bash
# Logseq Sync Cloud Function Deployment Script
# Deploys the logseq-sync function that updates Logseq journal files in GitHub

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-us-central1}"
BUCKET_NAME="${GCS_BUCKET:-}"
GITHUB_REPO="${LOGSEQ_GITHUB_REPO:-}"
GITHUB_TOKEN="${LOGSEQ_GITHUB_TOKEN:-}"
GITHUB_BRANCH="${LOGSEQ_GITHUB_BRANCH:-main}"
JOURNAL_PATH="${LOGSEQ_JOURNAL_PATH:-journals}"
FUNCTION_NAME="logseq-sync"
PUBSUB_TOPIC="otter-transcript-events"

# Validate required configuration
if [ -z "$PROJECT_ID" ]; then
    echo "Error: GCP_PROJECT environment variable is required"
    echo "Set it with: export GCP_PROJECT=your-project-id"
    exit 1
fi

if [ -z "$BUCKET_NAME" ]; then
    echo "Error: GCS_BUCKET environment variable is required"
    echo "Set it with: export GCS_BUCKET=your-bucket-name"
    exit 1
fi

if [ -z "$GITHUB_REPO" ]; then
    echo "Error: LOGSEQ_GITHUB_REPO environment variable is required"
    echo "Set it with: export LOGSEQ_GITHUB_REPO=owner/repo"
    exit 1
fi

if [ -z "$GITHUB_TOKEN" ]; then
    echo "Error: LOGSEQ_GITHUB_TOKEN environment variable is required"
    echo "Set it with: export LOGSEQ_GITHUB_TOKEN=ghp_xxxx"
    echo "Create a token at: https://github.com/settings/tokens"
    echo "Required scopes: repo (for private repos) or public_repo (for public)"
    exit 1
fi

SERVICE_ACCOUNT="${FUNCTION_NAME}-sa@${PROJECT_ID}.iam.gserviceaccount.com"
SECRET_NAME="logseq-github-token"

echo "=== Logseq Sync Deployment ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Bucket: $BUCKET_NAME"
echo "GitHub Repo: $GITHUB_REPO"
echo "GitHub Branch: $GITHUB_BRANCH"
echo "Journal Path: $JOURNAL_PATH"
echo "Topic: $PUBSUB_TOPIC"
echo ""

# Set the project
gcloud config set project "$PROJECT_ID"

# Enable required APIs
echo "Enabling required APIs..."
gcloud services enable \
    cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com \
    storage.googleapis.com \
    pubsub.googleapis.com \
    secretmanager.googleapis.com

# Create service account if it doesn't exist
echo "Setting up service account..."
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" &>/dev/null; then
    gcloud iam service-accounts create "${FUNCTION_NAME}-sa" \
        --display-name="Logseq Sync Cloud Function"
    echo "Waiting for service account to propagate..."
    sleep 10
fi

# Create or update the GitHub token secret
echo "Setting up GitHub token secret..."
if ! gcloud secrets describe "$SECRET_NAME" &>/dev/null; then
    echo -n "$GITHUB_TOKEN" | gcloud secrets create "$SECRET_NAME" \
        --data-file=- \
        --replication-policy="automatic"
else
    echo -n "$GITHUB_TOKEN" | gcloud secrets versions add "$SECRET_NAME" --data-file=-
fi

# Grant necessary permissions
echo "Granting IAM permissions..."

# Storage access for reading transcripts/tasks and writing state
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/storage.objectUser" \
    --quiet

# Secret Manager access for GitHub token
gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet

# Deploy the function
echo "Deploying function..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=. \
    --entry-point=process_task_event \
    --trigger-topic="$PUBSUB_TOPIC" \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="GCS_BUCKET=$BUCKET_NAME,GITHUB_REPO=$GITHUB_REPO,GITHUB_BRANCH=$GITHUB_BRANCH,LOGSEQ_JOURNAL_PATH=$JOURNAL_PATH,LOCAL_TIMEZONE=Pacific/Auckland" \
    --set-secrets="GITHUB_TOKEN=${SECRET_NAME}:latest" \
    --memory=256MB \
    --timeout=120s \
    --max-instances=5

echo ""
echo "=== Deployment Successful ==="
echo ""
echo "The logseq-sync function is now listening for transcript events."
echo "When task-extractor processes a transcript, this function will:"
echo "  1. Download the transcript and tasks from GCS"
echo "  2. Format them as Logseq blocks"
echo "  3. Update the journal file in GitHub"
echo ""
echo "Useful commands:"
echo ""
echo "  # View function logs"
echo "  gcloud functions logs read $FUNCTION_NAME --region=$REGION"
echo ""
echo "  # View recent logs (last 50 entries)"
echo "  gcloud functions logs read $FUNCTION_NAME --region=$REGION --limit=50"
echo ""
echo "  # Stream logs in real-time"
echo "  gcloud functions logs read $FUNCTION_NAME --region=$REGION --limit=10 --format='value(log)'"
echo ""
echo "  # Check state file (synced transcripts)"
echo "  gsutil cat gs://$BUCKET_NAME/.logseq_sync_state.json | jq ."
echo ""
echo "  # Clear state to force re-sync (use with republish-events)"
echo "  gsutil rm gs://$BUCKET_NAME/.logseq_sync_state.json"
echo ""
echo "  # View GitHub token secret versions"
echo "  gcloud secrets versions list $SECRET_NAME"
echo ""
echo "  # Update GitHub token"
echo "  echo -n 'new_token' | gcloud secrets versions add $SECRET_NAME --data-file=-"
