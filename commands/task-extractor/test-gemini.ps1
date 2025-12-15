# Test Gemini API Access
# Run this script to verify Gemini models are accessible in your GCP project
#
# Based on Google Cloud documentation (Dec 2025):
# https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models
#
# Available Gemini models on Vertex AI:
#   - gemini-2.5-flash (recommended for most use cases)
#   - gemini-2.5-pro
#   - gemini-2.5-flash-lite
#   - gemini-2.0-flash
#   - gemini-2.0-flash-lite

param(
    [string]$ProjectId = $env:GCP_PROJECT,
    [string]$Region = $env:GCP_REGION,
    [string]$Model = "gemini-2.5-flash",
    [switch]$ListModels
)

if (-not $ProjectId) {
    Write-Host "Error: GCP_PROJECT environment variable is required" -ForegroundColor Red
    Write-Host "Set it with: `$env:GCP_PROJECT = 'your-project-id'"
    exit 1
}

if (-not $Region) {
    $Region = "us-central1"
}

Write-Host "=== Vertex AI Gemini Test ===" -ForegroundColor Cyan
Write-Host "Project: $ProjectId"
Write-Host "Region: $Region"
Write-Host ""

# Get access token
Write-Host "Getting access token..." -ForegroundColor Yellow
$token = gcloud auth print-access-token
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Failed to get access token. Run 'gcloud auth login' first." -ForegroundColor Red
    exit 1
}

# List available models if requested
if ($ListModels) {
    Write-Host ""
    Write-Host "=== Testing Gemini Models ===" -ForegroundColor Cyan
    Write-Host ""

    # Current Gemini models on Vertex AI (Dec 2025)
    # Source: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models
    $knownModels = @(
        # Gemini 2.5 (Latest GA)
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-2.5-flash-lite",
        # Gemini 2.0
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        # Legacy (may still work)
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-pro"
    )

    Write-Host "Testing Gemini model names in $Region..." -ForegroundColor Yellow
    Write-Host "(Based on https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models)"
    Write-Host ""

    $workingModels = @()

    foreach ($testModel in $knownModels) {
        $testUrl = "https://$Region-aiplatform.googleapis.com/v1/projects/$ProjectId/locations/$Region/publishers/google/models/${testModel}:generateContent"
        $testBody = @{
            contents = @(@{ parts = @(@{ text = "Hi" }) })
        } | ConvertTo-Json -Depth 10

        try {
            $null = Invoke-RestMethod -Uri $testUrl -Method POST -Headers @{
                "Authorization" = "Bearer $token"
                "Content-Type" = "application/json"
            } -Body $testBody -ErrorAction Stop

            Write-Host "  [OK] $testModel" -ForegroundColor Green
            $workingModels += $testModel
        } catch {
            $statusCode = $_.Exception.Response.StatusCode.value__
            $errorMsg = ""
            try {
                $errorBody = $_.ErrorDetails.Message | ConvertFrom-Json
                $errorMsg = $errorBody.error.message
            } catch {}

            if ($statusCode -eq 404) {
                Write-Host "  [--] $testModel (not found in region)" -ForegroundColor DarkGray
            } elseif ($statusCode -eq 403) {
                Write-Host "  [!!] $testModel (permission denied)" -ForegroundColor Yellow
            } elseif ($statusCode -eq 400) {
                Write-Host "  [--] $testModel (invalid model)" -ForegroundColor DarkGray
            } else {
                Write-Host "  [??] $testModel (error $statusCode)" -ForegroundColor Red
                if ($errorMsg) {
                    Write-Host "       $errorMsg" -ForegroundColor DarkGray
                }
            }
        }
    }

    Write-Host ""
    if ($workingModels.Count -gt 0) {
        Write-Host "=== Working Models ===" -ForegroundColor Green
        foreach ($m in $workingModels) {
            Write-Host "  $m" -ForegroundColor White
        }
        Write-Host ""
        Write-Host "Recommended model for task-extractor:" -ForegroundColor Cyan
        Write-Host "  model = GenerativeModel(`"$($workingModels[0])`")"
    } else {
        Write-Host "No working models found!" -ForegroundColor Red
        Write-Host ""
        Write-Host "You need to:" -ForegroundColor Yellow
        Write-Host "  1. Enable Vertex AI API:"
        Write-Host "     gcloud services enable aiplatform.googleapis.com --project=$ProjectId"
        Write-Host ""
        Write-Host "  2. Enable Gemini in Model Garden (REQUIRED):"
        Write-Host "     https://console.cloud.google.com/vertex-ai/model-garden?project=$ProjectId"
        Write-Host "     Search for 'Gemini' and click 'Enable' on the model you want"
        Write-Host ""
        Write-Host "  3. Ensure billing is enabled for your project"
    }

    Write-Host ""
    Write-Host "To test a specific model:" -ForegroundColor Cyan
    Write-Host "  .\test-gemini.ps1 -Model gemini-2.5-flash"
    exit 0
}

# Test a specific model
Write-Host "Model: $Model"
Write-Host ""

# Build the API URL
$apiUrl = "https://$Region-aiplatform.googleapis.com/v1/projects/$ProjectId/locations/$Region/publishers/google/models/${Model}:generateContent"

Write-Host "API URL: $apiUrl" -ForegroundColor Gray
Write-Host ""

# Build request body
$body = @{
    contents = @(
        @{
            parts = @(
                @{
                    text = "Say 'Hello, Gemini is working!' in exactly those words."
                }
            )
        }
    )
} | ConvertTo-Json -Depth 10

Write-Host "Sending test request..." -ForegroundColor Yellow
Write-Host ""

try {
    $response = Invoke-RestMethod -Uri $apiUrl -Method POST -Headers @{
        "Authorization" = "Bearer $token"
        "Content-Type" = "application/json"
    } -Body $body

    Write-Host "=== SUCCESS ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Response:" -ForegroundColor Cyan

    # Extract the text response
    $text = $response.candidates[0].content.parts[0].text
    Write-Host $text
    Write-Host ""
    Write-Host "Model '$Model' is working!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Update task-extractor/main.py with:" -ForegroundColor Cyan
    Write-Host "  model = GenerativeModel(`"$Model`")"

} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    $errorBody = $_.ErrorDetails.Message

    Write-Host "=== ERROR ===" -ForegroundColor Red
    Write-Host "Status Code: $statusCode" -ForegroundColor Red
    Write-Host ""

    if ($errorBody) {
        $errorJson = $errorBody | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($errorJson) {
            Write-Host "Error: $($errorJson.error.message)" -ForegroundColor Red
            Write-Host ""

            if ($statusCode -eq 404 -or $errorBody -match "not found") {
                Write-Host "=== Model Not Found ===" -ForegroundColor Yellow
                Write-Host "The model '$Model' is not available."
                Write-Host ""
                Write-Host "Run: .\test-gemini.ps1 -ListModels"
                Write-Host "To see which models work in your project."
            }
            elseif ($statusCode -eq 403 -or $errorBody -match "permission") {
                Write-Host "=== Permission Denied ===" -ForegroundColor Yellow
                Write-Host "You need to enable Gemini in Model Garden:"
                Write-Host "  https://console.cloud.google.com/vertex-ai/model-garden?project=$ProjectId"
                Write-Host ""
                Write-Host "1. Search for 'Gemini'"
                Write-Host "2. Click on the model (e.g., Gemini 2.5 Flash)"
                Write-Host "3. Click 'Enable' or 'Get Started'"
            }
        } else {
            Write-Host $errorBody
        }
    } else {
        Write-Host $_.Exception.Message -ForegroundColor Red
    }

    Write-Host ""
    Write-Host "=== Try ===" -ForegroundColor Yellow
    Write-Host ".\test-gemini.ps1 -ListModels"
}
