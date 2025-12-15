#!/bin/bash
# Task Extractor Cloud Function Deployment Script
# Deploys the task-extractor function that processes transcript events

set -e

# Configuration
PROJECT_ID="${GCP_PROJECT:-}"
REGION="${GCP_REGION:-us-central1}"
BUCKET_NAME="${GCS_BUCKET:-}"
FUNCTION_NAME="task-extractor"
PUBSUB_INPUT_TOPIC="otter-transcript-events"
PUBSUB_OUTPUT_TOPIC="task-extracted-events"

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

echo "=== Task Extractor Deployment ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Bucket: $BUCKET_NAME"
echo "Input Topic: $PUBSUB_INPUT_TOPIC"
echo "Output Topic: $PUBSUB_OUTPUT_TOPIC"
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
    aiplatform.googleapis.com

# Create service account if it doesn't exist
echo "Setting up service account..."
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" &>/dev/null; then
    gcloud iam service-accounts create "${FUNCTION_NAME}-sa" \
        --display-name="Task Extractor Cloud Function"
fi

# Grant necessary permissions
echo "Granting IAM permissions..."

# Storage access for reading transcripts and writing tasks
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/storage.objectUser" \
    --quiet

# Vertex AI access for Gemini
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/aiplatform.user" \
    --quiet

# Pub/Sub publisher access for publishing tasks.extracted events
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/pubsub.publisher" \
    --quiet

# Create output Pub/Sub topic if it doesn't exist
echo "Creating Pub/Sub output topic..."
if ! gcloud pubsub topics describe "$PUBSUB_OUTPUT_TOPIC" &>/dev/null; then
    gcloud pubsub topics create "$PUBSUB_OUTPUT_TOPIC"
    echo "Created topic: $PUBSUB_OUTPUT_TOPIC"
else
    echo "Topic already exists: $PUBSUB_OUTPUT_TOPIC"
fi

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
    --trigger-topic="$PUBSUB_INPUT_TOPIC" \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="GCP_PROJECT=$PROJECT_ID,GCS_BUCKET=$BUCKET_NAME,PUBSUB_TOPIC=$PUBSUB_OUTPUT_TOPIC,LOCAL_TIMEZONE=Pacific/Auckland" \
    --memory=512MB \
    --timeout=120s \
    --max-instances=10

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
echo "The task-extractor function is now listening for transcript events."
echo "When otter-sync uploads a new transcript, this function will:"
echo "  1. Download the transcript from GCS"
echo "  2. Use Gemini to extract tasks and action items"
echo "  3. Save the tasks to gs://$BUCKET_NAME/tasks/"
echo "  4. Publish a 'tasks.extracted' event to $PUBSUB_OUTPUT_TOPIC"
echo ""
echo "=== Event Schema ==="
echo ""
echo "tasks.extracted events are published with this payload:"
echo '  {'
echo '    "event_type": "tasks.extracted",'
echo '    "transcript_id": "abc123",'
echo '    "transcript_title": "Team Meeting",'
echo '    "transcript_topic": "Work/Meetings",'
echo '    "task_count": 5,'
echo '    "gcs_path": "gs://bucket/tasks/2024-01-15_Team_Meeting_abc123.json",'
echo '    "gcs_bucket": "bucket-name",'
echo '    "gcs_blob": "tasks/2024-01-15_Team_Meeting_abc123.json",'
echo '    "transcript_created_at": "2024-01-15T10:30:00+13:00",'
echo '    "extracted_at": "2024-01-15T11:00:00+13:00"'
echo '  }'
echo ""
echo "=== Subscribe to Events ==="
echo ""
echo "  # Create a subscription to process task events"
echo "  gcloud pubsub subscriptions create my-task-handler \\"
echo "    --topic=$PUBSUB_OUTPUT_TOPIC \\"
echo "    --push-endpoint=https://your-function-url"
echo ""
echo "  # Or pull events manually for testing"
echo "  gcloud pubsub subscriptions create task-test-sub --topic=$PUBSUB_OUTPUT_TOPIC"
echo "  gcloud pubsub subscriptions pull task-test-sub --auto-ack"
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
echo "  # List extracted tasks in bucket"
echo "  gsutil ls gs://$BUCKET_NAME/tasks/"
echo ""
echo "  # View a specific task file"
echo "  gsutil cat gs://$BUCKET_NAME/tasks/FILENAME.json | jq ."
echo ""
echo "  # Check state file (processed transcripts)"
echo "  gsutil cat gs://$BUCKET_NAME/.task_extractor_state.json | jq ."
echo ""
echo "  # Clear state to force reprocessing (use with republish-events)"
echo "  gsutil rm gs://$BUCKET_NAME/.task_extractor_state.json"
echo ""
echo "  # Upload custom topic taxonomy"
echo "  gsutil cp topic_taxonomy.json gs://$BUCKET_NAME/topic_taxonomy.json"
