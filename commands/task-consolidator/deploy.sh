#!/bin/bash
# Task Consolidator Cloud Function Deployment Script
# Deploys the task-consolidator function that consolidates extracted tasks

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-us-central1}"
BUCKET_NAME="${GCS_BUCKET:-}"
FUNCTION_NAME="task-consolidator"
PUBSUB_INPUT_TOPIC="task-extracted-events"

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

echo "=== Task Consolidator Deployment ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Bucket: $BUCKET_NAME"
echo "Input Topic: $PUBSUB_INPUT_TOPIC"
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
        --display-name="Task Consolidator Cloud Function"
fi

# Grant necessary permissions
echo "Granting IAM permissions..."

# Storage access for reading task files and writing consolidated file
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/storage.objectUser" \
    --quiet

# Get the project number for Pub/Sub service account
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
PUBSUB_SA="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"

# Deploy the Pub/Sub triggered function
echo "Deploying Pub/Sub triggered function..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=. \
    --entry-point=process_tasks_event \
    --trigger-topic="$PUBSUB_INPUT_TOPIC" \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="GCS_BUCKET=$BUCKET_NAME,LOCAL_TIMEZONE=Pacific/Auckland" \
    --memory=256MB \
    --timeout=60s \
    --max-instances=5

# Grant Pub/Sub permission to invoke the function (required for Gen2)
echo "Granting Pub/Sub invoker permission..."
gcloud run services add-iam-policy-binding "$FUNCTION_NAME" \
    --region="$REGION" \
    --member="serviceAccount:$PUBSUB_SA" \
    --role="roles/run.invoker" \
    --quiet

# Deploy the HTTP rebuild endpoint
echo "Deploying HTTP rebuild endpoint..."
gcloud functions deploy "${FUNCTION_NAME}-rebuild" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=. \
    --entry-point=rebuild_consolidated \
    --trigger-http \
    --allow-unauthenticated \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="GCS_BUCKET=$BUCKET_NAME,LOCAL_TIMEZONE=Pacific/Auckland" \
    --memory=512MB \
    --timeout=300s \
    --max-instances=1

# Deploy the HTTP get-tasks endpoint
echo "Deploying HTTP get-tasks endpoint..."
gcloud functions deploy "${FUNCTION_NAME}-get" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=. \
    --entry-point=get_tasks \
    --trigger-http \
    --allow-unauthenticated \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="GCS_BUCKET=$BUCKET_NAME,LOCAL_TIMEZONE=Pacific/Auckland" \
    --memory=256MB \
    --timeout=30s \
    --max-instances=10

# Get the function URLs
REBUILD_URL=$(gcloud functions describe "${FUNCTION_NAME}-rebuild" --region="$REGION" --format='value(serviceConfig.uri)')
GET_URL=$(gcloud functions describe "${FUNCTION_NAME}-get" --region="$REGION" --format='value(serviceConfig.uri)')

echo ""
echo "=== Deployment Successful ==="
echo ""
echo "The task-consolidator functions are now deployed:"
echo ""
echo "1. Pub/Sub Listener: $FUNCTION_NAME"
echo "   - Automatically consolidates new tasks when task-extractor finishes"
echo ""
echo "2. Rebuild Endpoint: ${FUNCTION_NAME}-rebuild"
echo "   - URL: $REBUILD_URL"
echo ""
echo "3. Get Tasks Endpoint: ${FUNCTION_NAME}-get"
echo "   - URL: $GET_URL"
echo ""
echo "Useful commands:"
echo ""
echo "  # View function logs"
echo "  gcloud functions logs read $FUNCTION_NAME --region=$REGION"
echo ""
echo "  # Rebuild consolidated file from all existing tasks"
echo "  curl \"$REBUILD_URL\""
echo ""
echo "  # Dry run (see what would be consolidated)"
echo "  curl \"$REBUILD_URL?dry_run=true\""
echo ""
echo "  # Get all tasks"
echo "  curl \"$GET_URL\" | jq ."
echo ""
echo "  # Get summary only"
echo "  curl \"$GET_URL?format=summary\" | jq ."
echo ""
echo "  # Filter by topic"
echo "  curl \"$GET_URL?topic=Work\" | jq ."
echo ""
echo "  # Filter by assignee"
echo "  curl \"$GET_URL?assignee=John\" | jq ."
echo ""
echo "  # Filter by priority"
echo "  curl \"$GET_URL?priority=high\" | jq ."
echo ""
echo "  # Get tasks grouped by topic"
echo "  curl \"$GET_URL?format=by_topic\" | jq ."
echo ""
echo "  # View consolidated file directly"
echo "  gsutil cat gs://$BUCKET_NAME/tasks/consolidated_tasks.json | jq ."
echo ""
