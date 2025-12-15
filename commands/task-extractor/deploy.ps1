# Task Extractor Cloud Function Deployment Script (PowerShell)
# Deploys the task-extractor function that processes transcript events

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

$FUNCTION_NAME = "task-extractor"
$PUBSUB_TOPIC = "otter-transcript-events"
$SERVICE_ACCOUNT = "$FUNCTION_NAME-sa@$ProjectId.iam.gserviceaccount.com"

Write-Host "=== Task Extractor Deployment ===" -ForegroundColor Cyan
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
    pubsub.googleapis.com `
    aiplatform.googleapis.com

# Create service account if it doesn't exist
Write-Host "Setting up service account..." -ForegroundColor Yellow
$saExists = $false
$null = gcloud iam service-accounts describe $SERVICE_ACCOUNT 2>&1
if ($LASTEXITCODE -eq 0) {
    $saExists = $true
}

if (-not $saExists) {
    gcloud iam service-accounts create "$FUNCTION_NAME-sa" `
        --display-name="Task Extractor Cloud Function"
}

# Grant necessary permissions
Write-Host "Granting IAM permissions..." -ForegroundColor Yellow

# Storage access for reading transcripts and writing tasks
gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/storage.objectUser" `
    --quiet

# Vertex AI access for Gemini
gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/aiplatform.user" `
    --quiet

# Get the project number for Pub/Sub service account
$PROJECT_NUMBER = gcloud projects describe $ProjectId --format='value(projectNumber)'
$PUBSUB_SA = "service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"

# Deploy the function
Write-Host "Deploying function..." -ForegroundColor Yellow
gcloud functions deploy $FUNCTION_NAME `
    --gen2 `
    --region=$Region `
    --runtime=python312 `
    --source=. `
    --entry-point=process_transcript_event `
    --trigger-topic=$PUBSUB_TOPIC `
    --service-account=$SERVICE_ACCOUNT `
    --set-env-vars="GCP_PROJECT=$ProjectId,GCS_BUCKET=$BucketName,LOCAL_TIMEZONE=Pacific/Auckland" `
    --memory=512MB `
    --timeout=120s `
    --max-instances=10

if ($LASTEXITCODE -eq 0) {
    # Grant Pub/Sub permission to invoke the function (required for Gen2)
    Write-Host "Granting Pub/Sub invoker permission..." -ForegroundColor Yellow
    gcloud run services add-iam-policy-binding $FUNCTION_NAME `
        --region=$Region `
        --member="serviceAccount:$PUBSUB_SA" `
        --role="roles/run.invoker" `
        --quiet
    Write-Host ""
    Write-Host "=== Deployment Successful ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "The task-extractor function is now listening for transcript events."
    Write-Host "When otter-sync uploads a new transcript, this function will:"
    Write-Host "  1. Download the transcript from GCS"
    Write-Host "  2. Use Gemini to extract tasks and action items"
    Write-Host "  3. Save the tasks to gs://$BucketName/tasks/"
    Write-Host ""
    Write-Host "Useful commands:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  # View function logs"
    Write-Host "  gcloud functions logs read $FUNCTION_NAME --region=$Region"
    Write-Host ""
    Write-Host "  # View recent logs (last 50 entries)"
    Write-Host "  gcloud functions logs read $FUNCTION_NAME --region=$Region --limit=50"
    Write-Host ""
    Write-Host "  # List extracted tasks in bucket"
    Write-Host "  gsutil ls gs://$BucketName/tasks/"
    Write-Host ""
    Write-Host "  # View a specific task file"
    Write-Host "  gsutil cat gs://$BucketName/tasks/FILENAME.json"
    Write-Host ""
    Write-Host "  # Check state file (processed transcripts)"
    Write-Host "  gsutil cat gs://$BucketName/.task_extractor_state.json"
    Write-Host ""
    Write-Host "  # Clear state to force reprocessing (use with republish-events)"
    Write-Host "  gsutil rm gs://$BucketName/.task_extractor_state.json"
    Write-Host ""
    Write-Host "  # Upload custom topic taxonomy"
    Write-Host "  gsutil cp topic_taxonomy.json gs://$BucketName/topic_taxonomy.json"
} else {
    Write-Host ""
    Write-Host "=== Deployment Failed ===" -ForegroundColor Red
    Write-Host "Check the error messages above."
}
