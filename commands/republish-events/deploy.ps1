# Republish Events Cloud Function Deployment Script (PowerShell)
# Deploys the republish-events function for triggering downstream processing

param(
    [string]$ProjectId = $env:GCP_PROJECT,
    [string]$Region = $env:GCP_REGION,
    [string]$BucketName = $env:GCS_BUCKET
)

# Validate required parameters
if (-not $ProjectId) {
    Write-Host "Error: GCP_PROJECT environment variable is required" -ForegroundColor Red
    Write-Host "Set it with: `$env:GCP_PROJECT = 'your-project-id'"
    exit 1
}

if (-not $Region) {
    $Region = "us-central1"
    Write-Host "Using default region: $Region" -ForegroundColor Yellow
}

if (-not $BucketName) {
    Write-Host "Error: GCS_BUCKET environment variable is required" -ForegroundColor Red
    Write-Host "Set it with: `$env:GCS_BUCKET = 'your-bucket-name'"
    exit 1
}

$FUNCTION_NAME = "republish-events"
$PUBSUB_TOPIC = "otter-transcript-events"
$SERVICE_ACCOUNT = "$FUNCTION_NAME-sa@$ProjectId.iam.gserviceaccount.com"

Write-Host "=== Republish Events Deployment ===" -ForegroundColor Cyan
Write-Host "Project: $ProjectId"
Write-Host "Region: $Region"
Write-Host "Bucket: $BucketName"
Write-Host "Topic: $PUBSUB_TOPIC"
Write-Host ""

# Set the project
gcloud config set project $ProjectId

# Enable required APIs
Write-Host "Enabling required APIs..." -ForegroundColor Yellow
gcloud services enable `
    cloudfunctions.googleapis.com `
    cloudbuild.googleapis.com `
    storage.googleapis.com `
    pubsub.googleapis.com

# Create service account if it doesn't exist
Write-Host "Setting up service account..." -ForegroundColor Yellow
$saExists = $false
$null = gcloud iam service-accounts describe $SERVICE_ACCOUNT 2>&1
if ($LASTEXITCODE -eq 0) {
    $saExists = $true
}

if (-not $saExists) {
    gcloud iam service-accounts create "$FUNCTION_NAME-sa" `
        --display-name="Republish Events Cloud Function"
    Write-Host "Waiting for service account to propagate..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
}

# Grant necessary permissions
Write-Host "Granting IAM permissions..." -ForegroundColor Yellow

# Storage access for reading transcripts
gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/storage.objectViewer" `
    --quiet

# Pub/Sub access for publishing events
gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/pubsub.publisher" `
    --quiet

# Deploy the function
Write-Host "Deploying function..." -ForegroundColor Yellow
gcloud functions deploy $FUNCTION_NAME `
    --gen2 `
    --region=$Region `
    --runtime=python312 `
    --source=. `
    --entry-point=republish_events `
    --trigger-http `
    --no-allow-unauthenticated `
    --service-account=$SERVICE_ACCOUNT `
    --set-env-vars="GCP_PROJECT=$ProjectId,GCS_BUCKET=$BucketName,PUBSUB_TOPIC=$PUBSUB_TOPIC,LOCAL_TIMEZONE=Pacific/Auckland" `
    --memory=256MB `
    --timeout=540s `
    --max-instances=1

if ($LASTEXITCODE -eq 0) {
    # Get the function URL
    $FUNCTION_URL = gcloud functions describe $FUNCTION_NAME --region=$Region --format='value(serviceConfig.uri)'

    Write-Host ""
    Write-Host "=== Deployment Successful ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Function URL: $FUNCTION_URL"
    Write-Host ""
    Write-Host "Usage examples:"
    Write-Host ""
    Write-Host "  # Dry run - list all transcripts without publishing"
    Write-Host "  Invoke-RestMethod `"$FUNCTION_URL`?dry_run=true`""
    Write-Host ""
    Write-Host "  # Republish all transcripts"
    Write-Host "  Invoke-RestMethod `"$FUNCTION_URL`""
    Write-Host ""
    Write-Host "  # Republish transcripts from last 7 days"
    $weekAgo = (Get-Date).AddDays(-7).ToString("yyyy-MM-dd")
    Write-Host "  Invoke-RestMethod `"$FUNCTION_URL`?after=$weekAgo`""
    Write-Host ""
    Write-Host "  # Republish specific transcript"
    Write-Host "  Invoke-RestMethod `"$FUNCTION_URL`?transcript_id=abc123`""
    Write-Host ""
    Write-Host "  # Republish with topic filter"
    Write-Host "  Invoke-RestMethod `"$FUNCTION_URL`?topic=Personal/Journal`""
    Write-Host ""
    Write-Host "View logs:"
    Write-Host "   gcloud functions logs read $FUNCTION_NAME --region=$Region"
} else {
    Write-Host ""
    Write-Host "=== Deployment Failed ===" -ForegroundColor Red
    Write-Host "Check the error messages above."
}
