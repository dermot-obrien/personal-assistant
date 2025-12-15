# Deployment script for Otter.ai to GCS sync Cloud Function
# PowerShell equivalent of deploy.sh

$ErrorActionPreference = "Stop"

# Configuration - Update these values or set environment variables
$PROJECT_ID = if ($env:GCP_PROJECT) { $env:GCP_PROJECT } else { "your-project-id" }
$REGION = if ($env:GCP_REGION) { $env:GCP_REGION } else { "us-central1" }
$BUCKET_NAME = if ($env:GCS_BUCKET) { $env:GCS_BUCKET } else { "otter-transcripts" }
$FUNCTION_NAME = "otter-sync"
$PUBSUB_TOPIC = if ($env:PUBSUB_TOPIC) { $env:PUBSUB_TOPIC } else { "otter-transcript-events" }
$START_CYCLE_TOPIC = "start-cycle"
$SERVICE_ACCOUNT = "$FUNCTION_NAME-sa@$PROJECT_ID.iam.gserviceaccount.com"

Write-Host "=== Otter.ai to GCS Sync - Deployment ===" -ForegroundColor Cyan
Write-Host "Project: $PROJECT_ID"
Write-Host "Region: $REGION"
Write-Host "Bucket: $BUCKET_NAME"
Write-Host "Pub/Sub Topic (events): $PUBSUB_TOPIC"
Write-Host "Pub/Sub Topic (trigger): $START_CYCLE_TOPIC"
Write-Host ""

# Set project
gcloud config set project $PROJECT_ID

# Enable required APIs
Write-Host "Enabling required APIs..." -ForegroundColor Yellow
gcloud services enable `
    cloudfunctions.googleapis.com `
    cloudbuild.googleapis.com `
    cloudscheduler.googleapis.com `
    secretmanager.googleapis.com `
    storage.googleapis.com `
    pubsub.googleapis.com `
    cloudtrace.googleapis.com `
    eventarc.googleapis.com `
    run.googleapis.com

# Create service account if it doesn't exist
Write-Host "Setting up service account..." -ForegroundColor Yellow
$saExists = $false
$null = gcloud iam service-accounts describe $SERVICE_ACCOUNT 2>&1
if ($LASTEXITCODE -eq 0) {
    $saExists = $true
}
if (-not $saExists) {
    gcloud iam service-accounts create "$FUNCTION_NAME-sa" `
        --display-name="Otter Sync Cloud Function"

    # Wait for service account to propagate
    Write-Host "Waiting for service account to propagate..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
}

# Grant necessary roles
Write-Host "Granting IAM roles..." -ForegroundColor Yellow
gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/storage.objectAdmin" `
    --condition=None

gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/secretmanager.secretAccessor" `
    --condition=None

gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/pubsub.publisher" `
    --condition=None

gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/cloudtrace.agent" `
    --condition=None

# Grant Cloud Run invoker role (required for Cloud Scheduler to call the HTTP function)
gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/run.invoker" `
    --condition=None

# Allow service account to generate OIDC tokens for itself (required for Cloud Scheduler)
gcloud iam service-accounts add-iam-policy-binding $SERVICE_ACCOUNT `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/iam.serviceAccountTokenCreator"

# Get project number for Pub/Sub service agent
$PROJECT_NUMBER = (gcloud projects describe $PROJECT_ID --format="value(projectNumber)")

# Grant Pub/Sub service agent the invoker role (required for Pub/Sub triggered functions)
gcloud projects add-iam-policy-binding $PROJECT_ID `
    --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" `
    --role="roles/run.invoker" `
    --condition=None

# Create Pub/Sub topic for transcript events if it doesn't exist
Write-Host "Setting up Pub/Sub topics..." -ForegroundColor Yellow
$topicExists = $false
try {
    $null = gcloud pubsub topics describe $PUBSUB_TOPIC 2>$null
    if ($LASTEXITCODE -eq 0) { $topicExists = $true }
} catch { }
if (-not $topicExists) {
    Write-Host "Creating topic: $PUBSUB_TOPIC"
    gcloud pubsub topics create $PUBSUB_TOPIC
}

# Create Pub/Sub topic for start-cycle trigger if it doesn't exist
$startCycleExists = $false
try {
    $null = gcloud pubsub topics describe $START_CYCLE_TOPIC 2>$null
    if ($LASTEXITCODE -eq 0) { $startCycleExists = $true }
} catch { }
if (-not $startCycleExists) {
    Write-Host "Creating topic: $START_CYCLE_TOPIC"
    gcloud pubsub topics create $START_CYCLE_TOPIC
}

# Create GCS bucket if it doesn't exist
Write-Host "Setting up GCS bucket..." -ForegroundColor Yellow
$bucketExists = $false
try {
    $null = gcloud storage buckets describe "gs://$BUCKET_NAME" 2>$null
    if ($LASTEXITCODE -eq 0) { $bucketExists = $true }
} catch { }
if (-not $bucketExists) {
    Write-Host "Creating bucket: $BUCKET_NAME"
    gcloud storage buckets create "gs://$BUCKET_NAME" --location=$REGION
}

# Create secrets (if they don't exist) - you'll need to update values
Write-Host "Setting up secrets..." -ForegroundColor Yellow
$emailSecretExists = $false
try {
    $null = gcloud secrets describe otter-email 2>$null
    if ($LASTEXITCODE -eq 0) { $emailSecretExists = $true }
} catch { }
if (-not $emailSecretExists) {
    Write-Host "Creating otter-email secret..."
    "your-otter-email@example.com" | gcloud secrets create otter-email --data-file=-
    Write-Host "WARNING: Update the otter-email secret with your actual Otter.ai email" -ForegroundColor Red
}

$passwordSecretExists = $false
try {
    $null = gcloud secrets describe otter-password 2>$null
    if ($LASTEXITCODE -eq 0) { $passwordSecretExists = $true }
} catch { }
if (-not $passwordSecretExists) {
    Write-Host "Creating otter-password secret..."
    "your-otter-password" | gcloud secrets create otter-password --data-file=-
    Write-Host "WARNING: Update the otter-password secret with your actual Otter.ai password" -ForegroundColor Red
}

# Deploy HTTP-triggered Cloud Function
Write-Host "Deploying HTTP-triggered Cloud Function ($FUNCTION_NAME)..." -ForegroundColor Yellow
gcloud functions deploy $FUNCTION_NAME `
    --gen2 `
    --region=$REGION `
    --runtime=python312 `
    --source=. `
    --entry-point=sync_otter_transcripts `
    --trigger-http `
    --no-allow-unauthenticated `
    --service-account=$SERVICE_ACCOUNT `
    --set-env-vars="GCP_PROJECT=$PROJECT_ID,GCS_BUCKET=$BUCKET_NAME,PUBSUB_TOPIC=$PUBSUB_TOPIC" `
    --memory=256MB `
    --timeout=300s

# Get function URL
$FUNCTION_URL = gcloud functions describe $FUNCTION_NAME --region=$REGION --format="value(serviceConfig.uri)"
Write-Host "HTTP Function URL: $FUNCTION_URL"

# Deploy Pub/Sub-triggered Cloud Function
Write-Host "Deploying Pub/Sub-triggered Cloud Function ($FUNCTION_NAME-pubsub)..." -ForegroundColor Yellow
gcloud functions deploy "$FUNCTION_NAME-pubsub" `
    --gen2 `
    --region=$REGION `
    --runtime=python312 `
    --source=. `
    --entry-point=start_cycle `
    --trigger-topic=$START_CYCLE_TOPIC `
    --service-account=$SERVICE_ACCOUNT `
    --set-env-vars="GCP_PROJECT=$PROJECT_ID,GCS_BUCKET=$BUCKET_NAME,PUBSUB_TOPIC=$PUBSUB_TOPIC" `
    --memory=256MB `
    --timeout=300s

# Create Cloud Scheduler job
Write-Host "Setting up Cloud Scheduler..." -ForegroundColor Yellow
$SCHEDULER_NAME = "$FUNCTION_NAME-scheduler"

# Delete existing scheduler if present (ignore errors)
try {
    gcloud scheduler jobs delete $SCHEDULER_NAME --location=$REGION --quiet 2>$null
} catch {
    # Ignore if doesn't exist
}

# Create scheduler job to run every 30 minutes
gcloud scheduler jobs create http $SCHEDULER_NAME `
    --location=$REGION `
    --schedule="*/30 * * * *" `
    --uri=$FUNCTION_URL `
    --http-method=POST `
    --oidc-service-account-email=$SERVICE_ACCOUNT `
    --oidc-token-audience=$FUNCTION_URL

Write-Host ""
Write-Host "=== Deployment Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Deployed functions:" -ForegroundColor Cyan
Write-Host "  - $FUNCTION_NAME (HTTP trigger, scheduled every 30 min)"
Write-Host "  - $FUNCTION_NAME-pubsub (Pub/Sub trigger on '$START_CYCLE_TOPIC' topic)"
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Update the Otter.ai secrets with your credentials:"
Write-Host "   `"your-email@example.com`" | gcloud secrets versions add otter-email --data-file=-"
Write-Host "   `"your-password`" | gcloud secrets versions add otter-password --data-file=-"
Write-Host ""
Write-Host "2. Test the HTTP-triggered function:"
Write-Host "   gcloud functions call $FUNCTION_NAME --region=$REGION"
Write-Host ""
Write-Host "3. Test the Pub/Sub-triggered function:"
Write-Host "   gcloud pubsub topics publish $START_CYCLE_TOPIC --message='{}'"
Write-Host ""
Write-Host "4. View logs:"
Write-Host "   gcloud functions logs read $FUNCTION_NAME --region=$REGION"
Write-Host "   gcloud functions logs read $FUNCTION_NAME-pubsub --region=$REGION"
Write-Host ""
Write-Host "Transcripts will be saved to: gs://$BUCKET_NAME/transcripts/"
Write-Host "Events will be published to: projects/$PROJECT_ID/topics/$PUBSUB_TOPIC"
Write-Host ""
Write-Host "To trigger a sync via Pub/Sub:" -ForegroundColor Cyan
Write-Host "   gcloud pubsub topics publish $START_CYCLE_TOPIC --message='{}'"
Write-Host "   gcloud pubsub topics publish $START_CYCLE_TOPIC --message='{`"page_size`": 100}'"
