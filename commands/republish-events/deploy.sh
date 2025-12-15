#!/bin/bash
# Republish Events Cloud Function Deployment Script
# Deploys the republish-events function for triggering downstream processing

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-us-central1}"
BUCKET_NAME="${GCS_BUCKET:-}"
FUNCTION_NAME="republish-events"
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

echo "=== Republish Events Deployment ==="
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
        --display-name="Republish Events Cloud Function"
    echo "Waiting for service account to propagate..."
    sleep 10
fi

# Grant necessary permissions
echo "Granting IAM permissions..."

# Storage access for reading transcripts
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/storage.objectViewer" \
    --quiet

# Pub/Sub access for publishing events
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/pubsub.publisher" \
    --quiet

# Deploy the function
echo "Deploying function..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=. \
    --entry-point=republish_events \
    --trigger-http \
    --no-allow-unauthenticated \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="GCP_PROJECT=$PROJECT_ID,GCS_BUCKET=$BUCKET_NAME,PUBSUB_TOPIC=$PUBSUB_TOPIC,LOCAL_TIMEZONE=Pacific/Auckland" \
    --memory=256MB \
    --timeout=540s \
    --max-instances=1

# Get the function URL
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --format='value(serviceConfig.uri)')

echo ""
echo "=== Deployment Successful ==="
echo ""
echo "Function URL: $FUNCTION_URL"
echo ""
echo "Usage examples:"
echo ""
echo "  # Dry run - list all transcripts without publishing"
echo "  curl \"$FUNCTION_URL?dry_run=true\""
echo ""
echo "  # Republish all transcripts"
echo "  curl \"$FUNCTION_URL\""
echo ""
echo "  # Republish transcripts from last 7 days"
echo "  curl \"$FUNCTION_URL?after=$(date -d '7 days ago' +%Y-%m-%d)\""
echo ""
echo "  # Republish specific transcript"
echo "  curl \"$FUNCTION_URL?transcript_id=abc123\""
echo ""
echo "  # Republish with topic filter"
echo "  curl \"$FUNCTION_URL?topic=Personal/Journal\""
echo ""
echo "View logs:"
echo "   gcloud functions logs read $FUNCTION_NAME --region=$REGION"
