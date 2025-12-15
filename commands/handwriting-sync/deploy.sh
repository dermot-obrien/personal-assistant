#!/bin/bash
# Handwriting Sync Cloud Function Deployment Script
# Deploys the handwriting-sync function that OCRs handwritten journal images

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-us-central1}"
BUCKET_NAME="${GCS_BUCKET:-}"
GITHUB_REPO="${GITHUB_REPO:-}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
LOGSEQ_JOURNAL_PATH="${LOGSEQ_JOURNAL_PATH:-journals}"
FUNCTION_NAME="handwriting-sync"

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
    echo "Error: GITHUB_REPO environment variable is required"
    echo "Set it with: export GITHUB_REPO=owner/repo-name"
    exit 1
fi

if [ -z "$GITHUB_TOKEN" ]; then
    echo "Error: GITHUB_TOKEN environment variable is required"
    echo "Set it with: export GITHUB_TOKEN=ghp_xxxx"
    echo "Or store in Secret Manager and update the deployment script"
    exit 1
fi

SERVICE_ACCOUNT="${FUNCTION_NAME}-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=== Handwriting Sync Deployment ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Bucket: $BUCKET_NAME"
echo "GitHub Repo: $GITHUB_REPO"
echo "GitHub Branch: $GITHUB_BRANCH"
echo "Journal Path: $LOGSEQ_JOURNAL_PATH"
echo ""

# Set the project
gcloud config set project "$PROJECT_ID"

# Enable required APIs
echo "Enabling required APIs..."
gcloud services enable \
    cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com \
    storage.googleapis.com \
    aiplatform.googleapis.com \
    cloudscheduler.googleapis.com \
    run.googleapis.com

# Create service account if it doesn't exist
echo "Setting up service account..."
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" &>/dev/null; then
    gcloud iam service-accounts create "${FUNCTION_NAME}-sa" \
        --display-name="Handwriting Sync Cloud Function"
fi

# Grant necessary permissions
echo "Granting IAM permissions..."

# Storage access for writing transcripts and images
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/storage.objectUser" \
    --quiet

# Vertex AI access for Gemini Vision
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/aiplatform.user" \
    --quiet

# Deploy the function
echo "Deploying function..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=. \
    --entry-point=process_handwriting \
    --trigger-http \
    --allow-unauthenticated \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="GCP_PROJECT=$PROJECT_ID,GCS_BUCKET=$BUCKET_NAME,GITHUB_REPO=$GITHUB_REPO,GITHUB_TOKEN=$GITHUB_TOKEN,GITHUB_BRANCH=$GITHUB_BRANCH,LOGSEQ_JOURNAL_PATH=$LOGSEQ_JOURNAL_PATH,LOCAL_TIMEZONE=Pacific/Auckland" \
    --memory=1024MB \
    --timeout=540s \
    --max-instances=5

# Get the function URL
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --format='value(serviceConfig.uri)')

echo ""
echo "=== Deployment Successful ==="
echo ""
echo "Function URL: $FUNCTION_URL"
echo ""
echo "The handwriting-sync function is now deployed and can be triggered via HTTP."
echo ""
echo "What it does:"
echo "  1. Scans Logseq journal files in your GitHub repository"
echo "  2. Extracts image links from markdown"
echo "  3. Downloads images from GitHub"
echo "  4. Uses Gemini Vision to OCR handwritten text"
echo "  5. Saves transcripts and images to gs://$BUCKET_NAME/handwritten/"
echo "  6. Tracks processed images to avoid duplicates"
echo ""
echo "=== Testing the Function ==="
echo ""
echo "  # Test with dry run (list images without processing)"
echo "  curl '$FUNCTION_URL?dry_run=true'"
echo ""
echo "  # Process a specific date"
echo "  curl '$FUNCTION_URL?date=2024-01-15'"
echo ""
echo "  # Process journals from the last week"
echo "  curl '$FUNCTION_URL?after=2024-01-08&limit=10'"
echo ""
echo "  # Process all recent journals (up to 50)"
echo "  curl '$FUNCTION_URL'"
echo ""
echo "=== Useful Commands ==="
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
echo "  # List transcribed files"
echo "  gsutil ls gs://$BUCKET_NAME/handwritten/"
echo ""
echo "  # List transcripts with sizes"
echo "  gsutil ls -l gs://$BUCKET_NAME/handwritten/*_transcript.json"
echo ""
echo "  # View a transcript"
echo "  gsutil cat gs://$BUCKET_NAME/handwritten/FILENAME_transcript.json | jq ."
echo ""
echo "  # Check state file (processed images)"
echo "  gsutil cat gs://$BUCKET_NAME/.handwriting_sync_state.json | jq ."
echo ""
echo "  # Clear state to force reprocessing"
echo "  gsutil rm gs://$BUCKET_NAME/.handwriting_sync_state.json"
echo ""
echo "=== Optional: Set up Cloud Scheduler ==="
echo ""
echo "  # Create a daily schedule (runs at 6am)"
echo "  gcloud scheduler jobs create http handwriting-sync-daily \\"
echo "      --location=$REGION \\"
echo "      --schedule='0 6 * * *' \\"
echo "      --uri='$FUNCTION_URL?limit=20' \\"
echo "      --http-method=GET \\"
echo "      --oidc-service-account-email=$SERVICE_ACCOUNT"
echo ""
