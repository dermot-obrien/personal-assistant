# Logseq Sync Cloud Function Deployment Script (PowerShell)
# Deploys the logseq-sync function that updates Logseq journal files in GitHub

param(
    [string]$ProjectId = $env:GCP_PROJECT,
    [string]$Region = $env:GCP_REGION,
    [string]$BucketName = $env:GCS_BUCKET,
    [string]$GitHubRepo = $env:LOGSEQ_GITHUB_REPO,
    [string]$GitHubToken = $env:LOGSEQ_GITHUB_TOKEN,
    [string]$GitHubBranch = $env:LOGSEQ_GITHUB_BRANCH,
    [string]$JournalPath = $env:LOGSEQ_JOURNAL_PATH
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

if (-not $GitHubRepo) {
    Write-Host "Error: LOGSEQ_GITHUB_REPO environment variable is required" -ForegroundColor Red
    Write-Host "Set it with: `$env:LOGSEQ_GITHUB_REPO = 'owner/repo'"
    exit 1
}

if (-not $GitHubToken) {
    Write-Host "Error: LOGSEQ_GITHUB_TOKEN environment variable is required" -ForegroundColor Red
    Write-Host "Set it with: `$env:LOGSEQ_GITHUB_TOKEN = 'ghp_xxxx'"
    Write-Host "Create a token at: https://github.com/settings/tokens"
    Write-Host "Required scopes: repo (for private repos) or public_repo (for public)"
    exit 1
}

if (-not $GitHubBranch) {
    $GitHubBranch = "main"
}

if (-not $JournalPath) {
    $JournalPath = "journals"
}

$FUNCTION_NAME = "logseq-sync"
$PUBSUB_TOPIC = "otter-transcript-events"
$SERVICE_ACCOUNT = "$FUNCTION_NAME-sa@$ProjectId.iam.gserviceaccount.com"
$SECRET_NAME = "logseq-github-token"

Write-Host "=== Logseq Sync Deployment ===" -ForegroundColor Cyan
Write-Host "Project: $ProjectId"
Write-Host "Region: $Region"
Write-Host "Bucket: $BucketName"
Write-Host "GitHub Repo: $GitHubRepo"
Write-Host "GitHub Branch: $GitHubBranch"
Write-Host "Journal Path: $JournalPath"
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
    secretmanager.googleapis.com

# Create service account if it doesn't exist
Write-Host "Setting up service account..." -ForegroundColor Yellow
$saExists = $false
$null = gcloud iam service-accounts describe $SERVICE_ACCOUNT 2>&1
if ($LASTEXITCODE -eq 0) {
    $saExists = $true
}

if (-not $saExists) {
    gcloud iam service-accounts create "$FUNCTION_NAME-sa" `
        --display-name="Logseq Sync Cloud Function"
    Write-Host "Waiting for service account to propagate..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
}

# Create or update the GitHub token secret
Write-Host "Setting up GitHub token secret..." -ForegroundColor Yellow
$secretExists = $false
$null = gcloud secrets describe $SECRET_NAME 2>&1
if ($LASTEXITCODE -eq 0) {
    $secretExists = $true
}

if (-not $secretExists) {
    $GitHubToken | gcloud secrets create $SECRET_NAME `
        --data-file=- `
        --replication-policy="automatic"
} else {
    $GitHubToken | gcloud secrets versions add $SECRET_NAME --data-file=-
}

# Grant necessary permissions
Write-Host "Granting IAM permissions..." -ForegroundColor Yellow

# Storage access for reading transcripts/tasks and writing state
gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/storage.objectUser" `
    --quiet

# Secret Manager access for GitHub token
gcloud secrets add-iam-policy-binding $SECRET_NAME `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/secretmanager.secretAccessor" `
    --quiet

# Deploy the function
Write-Host "Deploying function..." -ForegroundColor Yellow
gcloud functions deploy $FUNCTION_NAME `
    --gen2 `
    --region=$Region `
    --runtime=python312 `
    --source=. `
    --entry-point=process_task_event `
    --trigger-topic=$PUBSUB_TOPIC `
    --service-account=$SERVICE_ACCOUNT `
    --set-env-vars="GCS_BUCKET=$BucketName,GITHUB_REPO=$GitHubRepo,GITHUB_BRANCH=$GitHubBranch,LOGSEQ_JOURNAL_PATH=$JournalPath,LOCAL_TIMEZONE=Pacific/Auckland" `
    --set-secrets="GITHUB_TOKEN=${SECRET_NAME}:latest" `
    --memory=256MB `
    --timeout=120s `
    --max-instances=5

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "=== Deployment Successful ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "The logseq-sync function is now listening for transcript events."
    Write-Host "When task-extractor processes a transcript, this function will:"
    Write-Host "  1. Download the transcript and tasks from GCS"
    Write-Host "  2. Format them as Logseq blocks"
    Write-Host "  3. Update the journal file in GitHub"
    Write-Host ""
    Write-Host "Useful commands:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  # View function logs"
    Write-Host "  gcloud functions logs read $FUNCTION_NAME --region=$Region"
    Write-Host ""
    Write-Host "  # View recent logs (last 50 entries)"
    Write-Host "  gcloud functions logs read $FUNCTION_NAME --region=$Region --limit=50"
    Write-Host ""
    Write-Host "  # Check state file (synced transcripts)"
    Write-Host "  gsutil cat gs://$BucketName/.logseq_sync_state.json"
    Write-Host ""
    Write-Host "  # Clear state to force re-sync (use with republish-events)"
    Write-Host "  gsutil rm gs://$BucketName/.logseq_sync_state.json"
    Write-Host ""
    Write-Host "  # View GitHub token secret versions"
    Write-Host "  gcloud secrets versions list $SECRET_NAME"
    Write-Host ""
    Write-Host "  # Update GitHub token"
    Write-Host "  'new_token' | gcloud secrets versions add $SECRET_NAME --data-file=-"
} else {
    Write-Host ""
    Write-Host "=== Deployment Failed ===" -ForegroundColor Red
    Write-Host "Check the error messages above."
}
