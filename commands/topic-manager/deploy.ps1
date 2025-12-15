# Topic Manager Deployment Script (PowerShell)
# Deploys the topic-manager microservice for taxonomy management

$ErrorActionPreference = "Stop"

# Configuration
$PROJECT_ID = $env:GCP_PROJECT
$REGION = if ($env:GCP_REGION) { $env:GCP_REGION } else { "us-central1" }
$BUCKET_NAME = $env:GCS_BUCKET
$FUNCTION_NAME = "topic-manager"

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

$SERVICE_ACCOUNT = "$FUNCTION_NAME-sa@$PROJECT_ID.iam.gserviceaccount.com"

Write-Host "=== Topic Manager Deployment ===" -ForegroundColor Cyan
Write-Host "Project: $PROJECT_ID"
Write-Host "Region: $REGION"
Write-Host "Bucket: $BUCKET_NAME"
Write-Host ""

# Set the project
gcloud config set project $PROJECT_ID

# Enable required APIs
Write-Host "Enabling required APIs..." -ForegroundColor Yellow
gcloud services enable `
    cloudfunctions.googleapis.com `
    cloudbuild.googleapis.com `
    storage.googleapis.com

# Create service account if it doesn't exist
Write-Host "Setting up service account..." -ForegroundColor Yellow
$saExists = gcloud iam service-accounts describe $SERVICE_ACCOUNT 2>$null
if (-not $saExists) {
    gcloud iam service-accounts create "$FUNCTION_NAME-sa" `
        --display-name="Topic Manager Cloud Function"
}

# Grant necessary permissions
Write-Host "Granting IAM permissions..." -ForegroundColor Yellow

gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/storage.objectUser" `
    --quiet

# Deploy the HTTP API function
Write-Host "Deploying Topic Manager API..." -ForegroundColor Yellow
gcloud functions deploy $FUNCTION_NAME `
    --gen2 `
    --region=$REGION `
    --runtime=python312 `
    --source=. `
    --entry-point=topic_api `
    --trigger-http `
    --allow-unauthenticated `
    --service-account=$SERVICE_ACCOUNT `
    --set-env-vars="GCS_BUCKET=$BUCKET_NAME,LOCAL_TIMEZONE=Pacific/Auckland" `
    --memory=256MB `
    --timeout=60s `
    --max-instances=10

# Get the function URL
$API_URL = gcloud functions describe $FUNCTION_NAME --region=$REGION --format='value(serviceConfig.uri)'

Write-Host ""
Write-Host "=== Deployment Successful ===" -ForegroundColor Green
Write-Host ""
Write-Host "Topic Manager API URL: $API_URL" -ForegroundColor Cyan
Write-Host ""
Write-Host "See deploy.sh for full API documentation and examples."
Write-Host ""
Write-Host "View logs:"
Write-Host "  gcloud functions logs read $FUNCTION_NAME --region=$REGION"
