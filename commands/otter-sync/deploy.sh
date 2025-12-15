#!/bin/bash
# Deployment script for Otter.ai to GCS sync Cloud Function

set -e

# Configuration - Update these values
PROJECT_ID="${GCP_PROJECT:-your-project-id}"
REGION="${GCP_REGION:-us-central1}"
BUCKET_NAME="${GCS_BUCKET:-otter-transcripts}"
FUNCTION_NAME="otter-sync"
PUBSUB_TOPIC="${PUBSUB_TOPIC:-otter-transcript-events}"
START_CYCLE_TOPIC="start-cycle"
SERVICE_ACCOUNT="${FUNCTION_NAME}-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "=== Otter.ai to GCS Sync - Deployment ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Bucket: $BUCKET_NAME"
echo "Pub/Sub Topic (events): $PUBSUB_TOPIC"
echo "Pub/Sub Topic (trigger): $START_CYCLE_TOPIC"

# Set project
gcloud config set project "$PROJECT_ID"

# Enable required APIs
echo "Enabling required APIs..."
gcloud services enable \
    cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com \
    cloudscheduler.googleapis.com \
    secretmanager.googleapis.com \
    storage.googleapis.com \
    pubsub.googleapis.com \
    cloudtrace.googleapis.com \
    eventarc.googleapis.com \
    run.googleapis.com

# Create service account if it doesn't exist
echo "Setting up service account..."
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" &>/dev/null; then
    gcloud iam service-accounts create "${FUNCTION_NAME}-sa" \
        --display-name="Otter Sync Cloud Function"

    # Wait for service account to propagate
    echo "Waiting for service account to propagate..."
    sleep 10
fi

# Grant necessary roles
echo "Granting IAM roles..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/storage.objectAdmin" \
    --condition=None

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/secretmanager.secretAccessor" \
    --condition=None

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/pubsub.publisher" \
    --condition=None

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/cloudtrace.agent" \
    --condition=None

# Grant Cloud Run invoker role (required for Cloud Scheduler to call the HTTP function)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/run.invoker" \
    --condition=None

# Allow service account to generate OIDC tokens for itself (required for Cloud Scheduler)
gcloud iam service-accounts add-iam-policy-binding "$SERVICE_ACCOUNT" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/iam.serviceAccountTokenCreator"

# Get project number for Pub/Sub service agent
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")

# Grant Pub/Sub service agent the invoker role (required for Pub/Sub triggered functions)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" \
    --role="roles/run.invoker" \
    --condition=None

# Create Pub/Sub topic for transcript events if it doesn't exist
echo "Setting up Pub/Sub topics..."
if ! gcloud pubsub topics describe "$PUBSUB_TOPIC" &>/dev/null; then
    gcloud pubsub topics create "$PUBSUB_TOPIC"
fi

# Create Pub/Sub topic for start-cycle trigger if it doesn't exist
if ! gcloud pubsub topics describe "$START_CYCLE_TOPIC" &>/dev/null; then
    gcloud pubsub topics create "$START_CYCLE_TOPIC"
fi

# Create GCS bucket if it doesn't exist
echo "Setting up GCS bucket..."
if ! gcloud storage buckets describe "gs://$BUCKET_NAME" &>/dev/null; then
    gcloud storage buckets create "gs://$BUCKET_NAME" --location="$REGION"
fi

# Create secrets (if they don't exist)
echo "Setting up secrets..."
if ! gcloud secrets describe otter-email &>/dev/null; then
    echo "Creating otter-email secret..."
    echo -n "your-otter-email@example.com" | gcloud secrets create otter-email --data-file=-
    echo "WARNING: Update the otter-email secret with your actual Otter.ai email"
fi

if ! gcloud secrets describe otter-password &>/dev/null; then
    echo "Creating otter-password secret..."
    echo -n "your-otter-password" | gcloud secrets create otter-password --data-file=-
    echo "WARNING: Update the otter-password secret with your actual Otter.ai password"
fi

# Deploy HTTP-triggered Cloud Function
echo "Deploying HTTP-triggered Cloud Function ($FUNCTION_NAME)..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=. \
    --entry-point=sync_otter_transcripts \
    --trigger-http \
    --no-allow-unauthenticated \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="GCP_PROJECT=$PROJECT_ID,GCS_BUCKET=$BUCKET_NAME,PUBSUB_TOPIC=$PUBSUB_TOPIC" \
    --memory=256MB \
    --timeout=300s

# Get function URL for scheduler
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --format='value(serviceConfig.uri)')
echo "HTTP Function URL: $FUNCTION_URL"

# Deploy Pub/Sub-triggered Cloud Function
echo "Deploying Pub/Sub-triggered Cloud Function (${FUNCTION_NAME}-pubsub)..."
gcloud functions deploy "${FUNCTION_NAME}-pubsub" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=. \
    --entry-point=start_cycle \
    --trigger-topic="$START_CYCLE_TOPIC" \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="GCP_PROJECT=$PROJECT_ID,GCS_BUCKET=$BUCKET_NAME,PUBSUB_TOPIC=$PUBSUB_TOPIC" \
    --memory=256MB \
    --timeout=300s

# Create Cloud Scheduler job for HTTP trigger
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
echo "Deployed functions:"
echo "  - $FUNCTION_NAME (HTTP trigger, scheduled every 30 min)"
echo "  - ${FUNCTION_NAME}-pubsub (Pub/Sub trigger on '$START_CYCLE_TOPIC' topic)"
echo ""
echo "Next steps:"
echo "1. Update the Otter.ai secrets with your credentials:"
echo "   echo -n 'your-email@example.com' | gcloud secrets versions add otter-email --data-file=-"
echo "   echo -n 'your-password' | gcloud secrets versions add otter-password --data-file=-"
echo ""
echo "2. Test the HTTP-triggered function:"
echo "   gcloud functions call $FUNCTION_NAME --region=$REGION"
echo ""
echo "3. Test the Pub/Sub-triggered function:"
echo "   gcloud pubsub topics publish $START_CYCLE_TOPIC --message='{}'"
echo ""
echo "4. View logs:"
echo "   gcloud functions logs read $FUNCTION_NAME --region=$REGION"
echo "   gcloud functions logs read ${FUNCTION_NAME}-pubsub --region=$REGION"
echo ""
echo "Transcripts will be saved to: gs://$BUCKET_NAME/transcripts/"
echo "Events will be published to: projects/$PROJECT_ID/topics/$PUBSUB_TOPIC"
echo ""
echo "To trigger a sync via Pub/Sub:"
echo "   gcloud pubsub topics publish $START_CYCLE_TOPIC --message='{}'"
echo "   gcloud pubsub topics publish $START_CYCLE_TOPIC --message='{\"page_size\": 100}'"
