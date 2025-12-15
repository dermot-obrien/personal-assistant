#!/bin/bash
# Deployment script for Plaud Note to GCS sync Cloud Function

set -e

# Configuration - Update these values
PROJECT_ID="${GCP_PROJECT:-your-project-id}"
REGION="${GCP_REGION:-us-central1}"
BUCKET_NAME="${GCS_BUCKET:-plaud-transcripts}"
FUNCTION_NAME="plaud-sync"
SERVICE_ACCOUNT="${FUNCTION_NAME}-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=== Plaud Note to GCS Sync - Deployment ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Bucket: $BUCKET_NAME"

# Set project
gcloud config set project "$PROJECT_ID"

# Enable required APIs
echo "Enabling required APIs..."
gcloud services enable \
    cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com \
    cloudscheduler.googleapis.com \
    secretmanager.googleapis.com \
    storage.googleapis.com

# Create service account if it doesn't exist
echo "Setting up service account..."
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" &>/dev/null; then
    gcloud iam service-accounts create "${FUNCTION_NAME}-sa" \
        --display-name="Plaud Sync Cloud Function"
fi

# Grant necessary roles
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/storage.objectAdmin" \
    --condition=None

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/secretmanager.secretAccessor" \
    --condition=None

# Create GCS bucket if it doesn't exist
echo "Setting up GCS bucket..."
if ! gsutil ls -b "gs://$BUCKET_NAME" &>/dev/null; then
    gsutil mb -l "$REGION" "gs://$BUCKET_NAME"
fi

# Create secret (if it doesn't exist)
echo "Setting up secrets..."
if ! gcloud secrets describe plaud-token &>/dev/null; then
    echo "Creating plaud-token secret..."
    echo -n "your-plaud-access-token" | gcloud secrets create plaud-token --data-file=-
    echo ""
    echo "========================================="
    echo "IMPORTANT: Update the plaud-token secret!"
    echo "========================================="
    echo ""
    echo "To get your Plaud access token:"
    echo "1. Login to https://web.plaud.ai"
    echo "2. Open browser DevTools (F12)"
    echo "3. Go to Application > Local Storage > web.plaud.ai"
    echo "4. Copy the 'access_token' value"
    echo ""
    echo "Then run:"
    echo "  echo -n 'YOUR_TOKEN_HERE' | gcloud secrets versions add plaud-token --data-file=-"
    echo ""
fi

# Deploy Cloud Function
echo "Deploying Cloud Function..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=. \
    --entry-point=sync_plaud_transcripts \
    --trigger-http \
    --allow-unauthenticated=false \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="GCP_PROJECT=$PROJECT_ID,GCS_BUCKET=$BUCKET_NAME" \
    --memory=256MB \
    --timeout=300s

# Get function URL
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --format='value(serviceConfig.uri)')
echo "Function URL: $FUNCTION_URL"

# Create Cloud Scheduler job
echo "Setting up Cloud Scheduler..."
SCHEDULER_NAME="${FUNCTION_NAME}-scheduler"

# Delete existing scheduler if present
gcloud scheduler jobs delete "$SCHEDULER_NAME" --location="$REGION" --quiet 2>/dev/null || true

# Create scheduler job to run every 30 minutes
gcloud scheduler jobs create http "$SCHEDULER_NAME" \
    --location="$REGION" \
    --schedule="*/30 * * * *" \
    --uri="$FUNCTION_URL" \
    --http-method=POST \
    --oidc-service-account-email="$SERVICE_ACCOUNT" \
    --oidc-token-audience="$FUNCTION_URL"

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Next steps:"
echo "1. Get your Plaud access token (see instructions above)"
echo "2. Update the secret:"
echo "   echo -n 'YOUR_TOKEN' | gcloud secrets versions add plaud-token --data-file=-"
echo ""
echo "3. Test the function manually:"
echo "   gcloud functions call $FUNCTION_NAME --region=$REGION"
echo ""
echo "4. View logs:"
echo "   gcloud functions logs read $FUNCTION_NAME --region=$REGION"
echo ""
echo "Transcripts will be saved to: gs://$BUCKET_NAME/plaud-transcripts/"
