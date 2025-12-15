# Graph Store Deployment Script (PowerShell)
# Deploys the graph-store microservice using Neo4j Aura backend

$ErrorActionPreference = "Stop"

# Configuration
$PROJECT_ID = $env:GCP_PROJECT
$REGION = if ($env:GCP_REGION) { $env:GCP_REGION } else { "us-central1" }
$FUNCTION_NAME = "graph-store"

# Neo4j Aura configuration
$NEO4J_URI = $env:NEO4J_URI
$NEO4J_USERNAME = if ($env:NEO4J_USERNAME) { $env:NEO4J_USERNAME } else { "neo4j" }
$NEO4J_PASSWORD = $env:NEO4J_PASSWORD

# Validate required configuration
if (-not $PROJECT_ID) {
    Write-Error "Error: GCP_PROJECT environment variable is required"
    Write-Host "Set it with: `$env:GCP_PROJECT = 'your-project-id'"
    exit 1
}

if (-not $NEO4J_URI -or -not $NEO4J_PASSWORD) {
    Write-Error "Error: NEO4J_URI and NEO4J_PASSWORD environment variables are required"
    Write-Host "Set them with:"
    Write-Host "  `$env:NEO4J_URI = 'neo4j+s://xxxxx.databases.neo4j.io'"
    Write-Host "  `$env:NEO4J_PASSWORD = 'your-password'"
    Write-Host ""
    Write-Host "Get a free Neo4j Aura instance at: https://neo4j.com/cloud/aura-free/"
    exit 1
}

$SERVICE_ACCOUNT = "$FUNCTION_NAME-sa@$PROJECT_ID.iam.gserviceaccount.com"

Write-Host "=== Graph Store Deployment ===" -ForegroundColor Cyan
Write-Host "Project: $PROJECT_ID"
Write-Host "Region: $REGION"
Write-Host "Neo4j URI: $NEO4J_URI"
Write-Host ""

# Set the project
gcloud config set project $PROJECT_ID

# Enable required APIs
Write-Host "Enabling required APIs..." -ForegroundColor Yellow
gcloud services enable `
    cloudfunctions.googleapis.com `
    cloudbuild.googleapis.com

# Create service account if it doesn't exist
Write-Host "Setting up service account..." -ForegroundColor Yellow
$saExists = $false
try {
    $null = gcloud iam service-accounts describe $SERVICE_ACCOUNT 2>&1
    $saExists = $LASTEXITCODE -eq 0
} catch {
    $saExists = $false
}
if (-not $saExists) {
    gcloud iam service-accounts create "$FUNCTION_NAME-sa" `
        --display-name="Graph Store Cloud Function"
}

# Build environment variables
$ENV_VARS = "NEO4J_URI=$NEO4J_URI,NEO4J_USERNAME=$NEO4J_USERNAME,NEO4J_PASSWORD=$NEO4J_PASSWORD,LOCAL_TIMEZONE=Pacific/Auckland"

# Deploy the HTTP API function
Write-Host "Deploying Graph Store API..." -ForegroundColor Yellow
gcloud functions deploy $FUNCTION_NAME `
    --gen2 `
    --region=$REGION `
    --runtime=python312 `
    --source=. `
    --entry-point=graph_api `
    --trigger-http `
    --allow-unauthenticated `
    --service-account=$SERVICE_ACCOUNT `
    --set-env-vars="$ENV_VARS" `
    --memory=512MB `
    --timeout=120s `
    --max-instances=10

# Get the function URL
$API_URL = gcloud functions describe $FUNCTION_NAME --region=$REGION --format='value(serviceConfig.uri)'

Write-Host ""
Write-Host "=== Deployment Successful ===" -ForegroundColor Green
Write-Host ""
Write-Host "Graph Store API URL: $API_URL" -ForegroundColor Cyan
Write-Host "Backend: Neo4j Aura"
Write-Host "Free Tier Limits: 200k nodes, 400k relationships" -ForegroundColor Yellow
Write-Host ""
Write-Host "See deploy.sh for full API documentation and examples."
Write-Host ""
Write-Host "View logs:"
Write-Host "  gcloud functions logs read $FUNCTION_NAME --region=$REGION"
