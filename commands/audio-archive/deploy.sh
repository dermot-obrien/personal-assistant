#!/bin/bash
# Audio Archive Cloud Function Deployment Script
# Deploys the audio-archive function that downloads and stores audio files

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-us-central1}"
BUCKET_NAME="${GCS_BUCKET:-}"
FUNCTION_NAME="audio-archive"
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

SERVICE_ACCOUNT="${FUNCTION_NAME}-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=== Audio Archive Deployment ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Bucket: $BUCKET_NAME"
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
    pubsub.googleapis.com

# Create service account if it doesn't exist
echo "Setting up service account..."
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" &>/dev/null; then
    gcloud iam service-accounts create "${FUNCTION_NAME}-sa" \
        --display-name="Audio Archive Cloud Function"
fi

# Grant necessary permissions
echo "Granting IAM permissions..."

# Storage access for reading transcripts and writing audio files
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/storage.objectUser" \
    --quiet

# Get the project number for Pub/Sub service account
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
PUBSUB_SA="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"

# Deploy the function
echo "Deploying function..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=. \
    --entry-point=process_transcript_event \
    --trigger-topic="$PUBSUB_TOPIC" \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="GCS_BUCKET=$BUCKET_NAME,LOCAL_TIMEZONE=Pacific/Auckland" \
    --memory=1024MB \
    --timeout=540s \
    --max-instances=5

# Grant Pub/Sub permission to invoke the function (required for Gen2)
echo "Granting Pub/Sub invoker permission..."
gcloud run services add-iam-policy-binding "$FUNCTION_NAME" \
    --region="$REGION" \
    --member="serviceAccount:$PUBSUB_SA" \
    --role="roles/run.invoker" \
    --quiet

echo ""
echo "=== Deployment Successful ==="
echo ""
echo "The audio-archive function is now listening for transcript events."
echo "When otter-sync uploads a new transcript, this function will:"
echo "  1. Download the transcript from GCS"
echo "  2. Extract the audio URL"
echo "  3. Download the audio file"
echo "  4. Save to gs://$BUCKET_NAME/audio/"
echo "  5. Update transcript with audio path reference"
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
echo "  # List archived audio files"
echo "  gsutil ls gs://$BUCKET_NAME/audio/"
echo ""
echo "  # List audio files with sizes"
echo "  gsutil ls -l gs://$BUCKET_NAME/audio/"
echo ""
echo "  # Check state file (processed transcripts)"
echo "  gsutil cat gs://$BUCKET_NAME/.audio_archive_state.json | jq ."
echo ""
echo "  # Clear state to force re-archiving (use with republish-events)"
echo "  gsutil rm gs://$BUCKET_NAME/.audio_archive_state.json"
echo ""
echo "  # Download an audio file"
echo "  gsutil cp gs://$BUCKET_NAME/audio/FILENAME.mp3 ./local_file.mp3"
