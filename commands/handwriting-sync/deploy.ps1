# Handwriting Sync Cloud Function Deployment Script (PowerShell)
# Deploys the handwriting-sync function that OCRs handwritten journal images

param(
    [string]$ProjectId = $env:GCP_PROJECT,
    [string]$Region = $env:GCP_REGION,
    [string]$BucketName = $env:GCS_BUCKET,
    [string]$GitHubRepo = $env:GITHUB_REPO,
    [string]$GitHubToken = $env:GITHUB_TOKEN,
    [string]$GitHubBranch = $env:GITHUB_BRANCH,
    [string]$LogseqJournalPath = $env:LOGSEQ_JOURNAL_PATH
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
    Write-Host "Error: GITHUB_REPO environment variable is required" -ForegroundColor Red
    Write-Host "Set it with: `$env:GITHUB_REPO = 'owner/repo-name'"
    exit 1
}

if (-not $GitHubToken) {
    Write-Host "Error: GITHUB_TOKEN environment variable is required" -ForegroundColor Red
    Write-Host "Set it with: `$env:GITHUB_TOKEN = 'ghp_xxxx'"
    exit 1
}

if (-not $GitHubBranch) {
    $GitHubBranch = "main"
}

if (-not $LogseqJournalPath) {
    $LogseqJournalPath = "journals"
}

$FUNCTION_NAME = "handwriting-sync"
$SERVICE_ACCOUNT = "$FUNCTION_NAME-sa@$ProjectId.iam.gserviceaccount.com"

Write-Host "=== Handwriting Sync Deployment ===" -ForegroundColor Cyan
Write-Host "Project: $ProjectId"
Write-Host "Region: $Region"
Write-Host "Bucket: $BucketName"
Write-Host "GitHub Repo: $GitHubRepo"
Write-Host "GitHub Branch: $GitHubBranch"
Write-Host "Journal Path: $LogseqJournalPath"
Write-Host ""

# Set the project
gcloud config set project $ProjectId

# Enable required APIs
Write-Host "Enabling required APIs..." -ForegroundColor Yellow
gcloud services enable `
    cloudfunctions.googleapis.com `
    cloudbuild.googleapis.com `
    storage.googleapis.com `
    aiplatform.googleapis.com `
    cloudscheduler.googleapis.com `
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
        --display-name="Handwriting Sync Cloud Function"
}

# Grant necessary permissions
Write-Host "Granting IAM permissions..." -ForegroundColor Yellow

# Storage access for writing transcripts and images
gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/storage.objectUser" `
    --quiet

# Vertex AI access for Gemini Vision
gcloud projects add-iam-policy-binding $ProjectId `
    --member="serviceAccount:$SERVICE_ACCOUNT" `
    --role="roles/aiplatform.user" `
    --quiet

# Deploy the function
Write-Host "Deploying function..." -ForegroundColor Yellow
gcloud functions deploy $FUNCTION_NAME `
    --gen2 `
    --region=$Region `
    --runtime=python312 `
    --source=. `
    --entry-point=process_handwriting `
    --trigger-http `
    --allow-unauthenticated `
    --service-account=$SERVICE_ACCOUNT `
    --set-env-vars="GCP_PROJECT=$ProjectId,GCS_BUCKET=$BucketName,GITHUB_REPO=$GitHubRepo,GITHUB_TOKEN=$GitHubToken,GITHUB_BRANCH=$GitHubBranch,LOGSEQ_JOURNAL_PATH=$LogseqJournalPath,LOCAL_TIMEZONE=Pacific/Auckland" `
    --memory=1024MB `
    --timeout=540s `
    --max-instances=5

if ($LASTEXITCODE -eq 0) {
    # Get the function URL
    $FUNCTION_URL = gcloud functions describe $FUNCTION_NAME --region=$Region --format='value(serviceConfig.uri)'

    Write-Host ""
    Write-Host "=== Deployment Successful ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Function URL: $FUNCTION_URL"
    Write-Host ""
    Write-Host "The handwriting-sync function is now deployed and can be triggered via HTTP."
    Write-Host ""
    Write-Host "What it does:"
    Write-Host "  1. Scans Logseq journal files in your GitHub repository"
    Write-Host "  2. Extracts image links from markdown"
    Write-Host "  3. Downloads images from GitHub"
    Write-Host "  4. Uses Gemini Vision to OCR handwritten text"
    Write-Host "  5. Saves transcripts and images to gs://$BucketName/handwritten/"
    Write-Host "  6. Tracks processed images to avoid duplicates"
    Write-Host ""
    Write-Host "=== Testing the Function ===" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  # Test with dry run (list images without processing)"
    Write-Host "  Invoke-RestMethod '$FUNCTION_URL`?dry_run=true'"
    Write-Host ""
    Write-Host "  # Process a specific date"
    Write-Host "  Invoke-RestMethod '$FUNCTION_URL`?date=2024-01-15'"
    Write-Host ""
    Write-Host "  # Process journals from the last week"
    Write-Host "  Invoke-RestMethod '$FUNCTION_URL`?after=2024-01-08&limit=10'"
    Write-Host ""
    Write-Host "  # Process all recent journals (up to 50)"
    Write-Host "  Invoke-RestMethod '$FUNCTION_URL'"
    Write-Host ""
    Write-Host "=== Useful Commands ===" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  # View function logs"
    Write-Host "  gcloud functions logs read $FUNCTION_NAME --region=$Region"
    Write-Host ""
    Write-Host "  # View recent logs (last 50 entries)"
    Write-Host "  gcloud functions logs read $FUNCTION_NAME --region=$Region --limit=50"
    Write-Host ""
    Write-Host "  # List transcribed files"
    Write-Host "  gsutil ls gs://$BucketName/handwritten/"
    Write-Host ""
    Write-Host "  # List transcripts with sizes"
    Write-Host "  gsutil ls -l gs://$BucketName/handwritten/*_transcript.json"
    Write-Host ""
    Write-Host "  # View a transcript"
    Write-Host "  gsutil cat gs://$BucketName/handwritten/FILENAME_transcript.json"
    Write-Host ""
    Write-Host "  # Check state file (processed images)"
    Write-Host "  gsutil cat gs://$BucketName/.handwriting_sync_state.json"
    Write-Host ""
    Write-Host "  # Clear state to force reprocessing"
    Write-Host "  gsutil rm gs://$BucketName/.handwriting_sync_state.json"
    Write-Host ""
    Write-Host "=== Optional: Set up Cloud Scheduler ===" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  # Create a daily schedule (runs at 6am)"
    Write-Host "  gcloud scheduler jobs create http handwriting-sync-daily \"
    Write-Host "      --location=$Region \"
    Write-Host "      --schedule='0 6 * * *' \"
    Write-Host "      --uri='$FUNCTION_URL`?limit=20' \"
    Write-Host "      --http-method=GET \"
    Write-Host "      --oidc-service-account-email=$SERVICE_ACCOUNT"
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "=== Deployment Failed ===" -ForegroundColor Red
    Write-Host "Check the error messages above."
}
