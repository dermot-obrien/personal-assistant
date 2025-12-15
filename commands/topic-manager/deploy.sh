#!/bin/bash
# Topic Manager Deployment Script
# Deploys the topic-manager microservice for taxonomy management

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-us-central1}"
BUCKET_NAME="${GCS_BUCKET:-}"
FUNCTION_NAME="topic-manager"

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

echo "=== Topic Manager Deployment ==="
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
        --display-name="Topic Manager Cloud Function"
fi

# Grant necessary permissions
echo "Granting IAM permissions..."

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/storage.objectUser" \
    --quiet

# Deploy the HTTP API function
echo "Deploying Topic Manager API..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --region="$REGION" \
    --runtime=python312 \
    --source=. \
    --entry-point=topic_api \
    --trigger-http \
    --allow-unauthenticated \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="GCS_BUCKET=$BUCKET_NAME,LOCAL_TIMEZONE=Pacific/Auckland" \
    --memory=256MB \
    --timeout=60s \
    --max-instances=10

# Get the function URL
API_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --format='value(serviceConfig.uri)')

echo ""
echo "=== Deployment Successful ==="
echo ""
echo "Topic Manager API URL: $API_URL"
echo ""
echo "API Endpoints:"
echo ""
echo "  # List all topics"
echo "  curl \"$API_URL\" | jq ."
echo ""
echo "  # Get hierarchical tree"
echo "  curl \"$API_URL/tree\" | jq ."
echo ""
echo "  # Get tree from a root"
echo "  curl \"$API_URL/tree?root=Work\" | jq ."
echo ""
echo "  # Search topics"
echo "  curl \"$API_URL/search?q=project\" | jq ."
echo ""
echo "  # Get topic by ID"
echo "  curl \"$API_URL/topic:work_projects\" | jq ."
echo ""
echo "  # Get topic by path"
echo "  curl \"$API_URL/path/Work/Projects\" | jq ."
echo ""
echo "  # Create a topic"
echo "  curl -X POST \"$API_URL\" \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"path\": \"Work/Projects/NewProject\", \"description\": \"New project\"}'"
echo ""
echo "  # Update a topic"
echo "  curl -X PUT \"$API_URL/topic:work_projects_newproject\" \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"description\": \"Updated description\"}'"
echo ""
echo "  # Get children of a topic"
echo "  curl \"$API_URL/topic:work/children\" | jq ."
echo ""
echo "  # Move a topic"
echo "  curl -X POST \"$API_URL/topic:work_old/move\" \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"new_parent_path\": \"Archive\"}'"
echo ""
echo "  # Merge topics"
echo "  curl -X POST \"$API_URL/merge\" \\"
echo "    -H 'Content-Type: application/json' \\"
echo "    -d '{\"source_id\": \"topic:old_topic\", \"target_id\": \"topic:main_topic\"}'"
echo ""
echo "  # Delete a topic"
echo "  curl -X DELETE \"$API_URL/topic:work_old\""
echo ""
echo "  # View logs"
echo "  gcloud functions logs read $FUNCTION_NAME --region=$REGION"
echo ""
