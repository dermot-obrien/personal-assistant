#!/bin/bash
# Task Manager Microservice Deployment Script
# Deploys the task-manager function that provides CRUD operations for tasks

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-us-central1}"
BUCKET_NAME="${GCS_BUCKET:-}"
FUNCTION_NAME="task-manager"

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

echo "=== Task Manager Deployment ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Bucket: $BUCKET_NAME"
echo ""

# Set the project
gcloud config set project "$PROJECT_ID"

# Enable required APIs
echo "Enabling required APIs..."
gcloud services enable \
    cloudfunctions.googleapis.com \
    cloudbuild.googleapis.com \
    storage.googleapis.com

# Create service account if it doesn't exist
echo "Setting up service account..."
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" &>/dev/null; then
    gcloud iam service-accounts create "${FUNCTION_NAME}-sa" \
        --display-name="Task Manager Cloud Function"
fi

# Grant necessary permissions
echo "Granting IAM permissions..."

# Storage access for reading/writing tasks
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/storage.objectUser" \
    --quiet

# Deploy the HTTP API function
echo "Deploying Task Manager API..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=. \
    --entry-point=task_api \
    --trigger-http \
    --allow-unauthenticated \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="GCS_BUCKET=$BUCKET_NAME,LOCAL_TIMEZONE=Pacific/Auckland,STORAGE_MODE=graph" \
    --memory=256MB \
    --timeout=60s \
    --max-instances=10

# Get the function URL
API_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --format='value(serviceConfig.uri)')

echo ""
echo "=== Deployment Successful ==="
echo ""
echo "Task Manager API URL: $API_URL"
echo "Storage Mode: graph (knowledge graph backend)"
echo ""
echo "API Endpoints:"
echo ""
echo "  # List all tasks"
echo "  curl \"$API_URL\" | jq ."
echo ""
echo "  # List with filters"
echo "  curl \"$API_URL?status=pending&priority=high\" | jq ."
echo "  curl \"$API_URL?topic=Work\" | jq ."
echo "  curl \"$API_URL?assignee=John\" | jq ."
echo "  curl \"$API_URL?q=search+term\" | jq ."
echo ""
echo "  # Get task statistics"
echo "  curl \"$API_URL/stats\" | jq ."
echo ""
echo "  # Get a specific task"
echo "  curl \"$API_URL/task:abc123\" | jq ."
echo ""
echo "  # Get LLM context for a task (GraphRAG)"
echo "  curl \"$API_URL/task:abc123/context?depth=2\" | jq ."
echo ""
echo "  # Create a new task"
echo "  curl -X POST \"$API_URL\" \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"description\": \"My task\", \"priority\": \"high\", \"primary_topic\": \"Work\"}'"
echo ""
echo "  # Update a task"
echo "  curl -X PUT \"$API_URL/task:abc123\" \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"priority\": \"low\"}'"
echo ""
echo "  # Complete a task"
echo "  curl -X POST \"$API_URL/task:abc123/complete\""
echo ""
echo "  # Reopen a task"
echo "  curl -X POST \"$API_URL/task:abc123/reopen\""
echo ""
echo "  # Delete a task"
echo "  curl -X DELETE \"$API_URL/task:abc123\""
echo ""
echo "  # Import from consolidated tasks (dry run)"
echo "  curl -X POST \"$API_URL/import?dry_run=true\" | jq ."
echo ""
echo "  # Import from consolidated tasks"
echo "  curl -X POST \"$API_URL/import\" | jq ."
echo ""
echo "  # View logs"
echo "  gcloud functions logs read $FUNCTION_NAME --region=$REGION"
echo ""
echo "Note: Set STORAGE_MODE=legacy to use the old managed/tasks.json format"
