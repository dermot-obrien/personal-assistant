# Task Consolidator Cloud Function Deployment Script (PowerShell)
# Deploys the task-consolidator function that consolidates extracted tasks

$ErrorActionPreference = "Stop"

# Configuration
$PROJECT_ID = $env:GCP_PROJECT
$REGION = if ($env:GCP_REGION) { $env:GCP_REGION } else { "us-central1" }
$BUCKET_NAME = $env:GCS_BUCKET
$FUNCTION_NAME = "task-consolidator"
$PUBSUB_INPUT_TOPIC = "task-extracted-events"

# Validate required configuration
if (-not $PROJECT_ID) {
    Write-Error "Error: GCP_PROJECT environment variable is required"
    Write-Host "Set it with: `$env:GCP_PROJECT = 'your-project-id'"
    exit 1
}

if (-not $BUCKET_NAME) {
    Write-Error "Error: GCS_BUCKET environment variable is required"
    Write-Host "Set it with: `$env:GCS_BUCKET = 'your-bucket-name'"
    exit 1
}

$SERVICE_ACCOUNT = "${FUNCTION_NAME}-sa@${PROJECT_ID}.iam.gserviceaccount.com"

Write-Host "=== Task Consolidator Deployment ===" -ForegroundColor Cyan
Write-Host "Project: $PROJECT_ID"
Write-Host "Region: $REGION"
Write-Host "Bucket: $BUCKET_NAME"
Write-Host "Input Topic: $PUBSUB_INPUT_TOPIC"
Write-Host ""

# Set the project
gcloud config set project $PROJECT_ID

# Enable required APIs
Write-Host "Enabling required APIs..." -ForegroundColor Yellow
gcloud services enable `
    cloudfunctions.googleapis.com `
    cloudbuild.googleapis.com `
    storage.googleapis.com `
    pubsub.googleapis.com

# Create service account if it doesn't exist
Write-Host "Setting up service account..." -ForegroundColor Yellow
$saExists = $null
try {
    $saExists = gcloud iam service-accounts describe $SERVICE_ACCOUNT 2>&1
} catch {
    # Ignore errors - account doesn't exist
}
if (-not $saExists -or $saExists -match "NOT_FOUND") {
    gcloud iam service-accounts create "${FUNCTION_NAME}-sa" `
        --display-name="Task Consolidator Cloud Function"
}

# Grant necessary permissions
Write-Host "Granting IAM permissions..." -ForegroundColor Yellow

# Storage access for reading task files and writing consolidated file
gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/storage.objectUser" `
    --quiet

# Get the project number for Pub/Sub service account
$PROJECT_NUMBER = gcloud projects describe $PROJECT_ID --format='value(projectNumber)'
$PUBSUB_SA = "service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"

# Deploy the Pub/Sub triggered function
Write-Host "Deploying Pub/Sub triggered function..." -ForegroundColor Yellow
gcloud functions deploy $FUNCTION_NAME `
    --gen2 `
    --region=$REGION `
    --runtime=python312 `
    --source=. `
    --entry-point=process_tasks_event `
    --trigger-topic=$PUBSUB_INPUT_TOPIC `
    --service-account=$SERVICE_ACCOUNT `
    --set-env-vars="GCS_BUCKET=$BUCKET_NAME,LOCAL_TIMEZONE=Pacific/Auckland" `
    --memory=256MB `
    --timeout=60s `
    --max-instances=5

# Grant Pub/Sub permission to invoke the function (required for Gen2)
Write-Host "Granting Pub/Sub invoker permission..." -ForegroundColor Yellow
gcloud run services add-iam-policy-binding $FUNCTION_NAME `
    --region=$REGION `
    --member="serviceAccount:$PUBSUB_SA" `
    --role="roles/run.invoker" `
    --quiet

# Deploy the HTTP rebuild endpoint
Write-Host "Deploying HTTP rebuild endpoint..." -ForegroundColor Yellow
gcloud functions deploy "${FUNCTION_NAME}-rebuild" `
    --gen2 `
    --region=$REGION `
    --runtime=python312 `
    --source=. `
    --entry-point=rebuild_consolidated `
    --trigger-http `
    --allow-unauthenticated `
    --service-account=$SERVICE_ACCOUNT `
    --set-env-vars="GCS_BUCKET=$BUCKET_NAME,LOCAL_TIMEZONE=Pacific/Auckland" `
    --memory=512MB `
    --timeout=300s `
    --max-instances=1

# Deploy the HTTP get-tasks endpoint
Write-Host "Deploying HTTP get-tasks endpoint..." -ForegroundColor Yellow
gcloud functions deploy "${FUNCTION_NAME}-get" `
    --gen2 `
    --region=$REGION `
    --runtime=python312 `
    --source=. `
    --entry-point=get_tasks `
    --trigger-http `
    --allow-unauthenticated `
    --service-account=$SERVICE_ACCOUNT `
    --set-env-vars="GCS_BUCKET=$BUCKET_NAME,LOCAL_TIMEZONE=Pacific/Auckland" `
    --memory=256MB `
    --timeout=30s `
    --max-instances=10

# Get the function URLs
$REBUILD_URL = gcloud functions describe "${FUNCTION_NAME}-rebuild" --region=$REGION --format='value(serviceConfig.uri)'
$GET_URL = gcloud functions describe "${FUNCTION_NAME}-get" --region=$REGION --format='value(serviceConfig.uri)'

Write-Host ""
Write-Host "=== Deployment Successful ===" -ForegroundColor Green
Write-Host ""
Write-Host "The task-consolidator functions are now deployed:"
Write-Host ""
Write-Host "1. Pub/Sub Listener: $FUNCTION_NAME"
Write-Host "   - Automatically consolidates new tasks when task-extractor finishes"
Write-Host ""
Write-Host "2. Rebuild Endpoint: ${FUNCTION_NAME}-rebuild"
Write-Host "   - URL: $REBUILD_URL"
Write-Host ""
Write-Host "3. Get Tasks Endpoint: ${FUNCTION_NAME}-get"
Write-Host "   - URL: $GET_URL"
Write-Host ""
Write-Host "Useful commands:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  # View function logs"
Write-Host "  gcloud functions logs read $FUNCTION_NAME --region=$REGION"
Write-Host ""
Write-Host "  # Rebuild consolidated file from all existing tasks"
Write-Host "  curl `"$REBUILD_URL`""
Write-Host ""
Write-Host "  # Get all tasks"
Write-Host "  curl `"$GET_URL`" | jq ."
Write-Host ""
Write-Host "  # Get summary only"
Write-Host "  curl `"$GET_URL?format=summary`" | jq ."
Write-Host ""
Write-Host "  # Filter by topic"
Write-Host "  curl `"$GET_URL?topic=Work`" | jq ."
Write-Host ""
Write-Host "  # View consolidated file directly"
Write-Host "  gsutil cat gs://$BUCKET_NAME/tasks/consolidated_tasks.json | jq ."
Write-Host ""
