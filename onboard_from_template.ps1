#Requires -Version 5.1
<#
.SYNOPSIS
    Onboard a new tenant using a template. Fully automated.
.EXAMPLE
    .\onboard_from_template.ps1 -TenantId "acme_clean" -Template "cleaning_service" `
        -BusinessName "Acme Cleaning" -ServiceArea "Brisbane metro" `
        -BasePrice "$150" -Phone "0400 123 456" -Email "hello@acme.com"
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [Parameter(Mandatory=$true)][string]$Template,
  [Parameter(Mandatory=$true)][string]$BusinessName,
  [Parameter(Mandatory=$false)][string]$ServiceArea = "Please ask for your suburb",
  [Parameter(Mandatory=$false)][string]$BasePrice = "Contact us for pricing",
  [Parameter(Mandatory=$false)][string]$Phone = "",
  [Parameter(Mandatory=$false)][string]$Email = "",
  [Parameter(Mandatory=$false)][string]$PrimaryColor = "#2563eb",
  [Parameter(Mandatory=$false)][switch]$SkipLLMVariants,
  [Parameter(Mandatory=$false)][switch]$SkipPromote
)

$ErrorActionPreference = "Stop"
$scriptDir = $PSScriptRoot
$tenantDir = Join-Path $scriptDir "tenants" $TenantId
$faqsPath = Join-Path $tenantDir "faqs.json"
$variantsPath = Join-Path $tenantDir "faqs_variants.json"

# Python executable
$pythonExe = Join-Path $scriptDir ".venv" "Scripts" "python.exe"
if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }

# Load admin token
$envPath = Join-Path $scriptDir ".env"
$adminToken = (Get-Content $envPath | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
$renderBaseUrl = "https://motionmade-fastapi.onrender.com"
$headers = @{ "Authorization" = "Bearer $adminToken"; "Content-Type" = "application/json" }

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  TEMPLATE ONBOARDING: $TenantId" -ForegroundColor Cyan
Write-Host "  Template: $Template" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Step 1: Create directories
Write-Host "`n[1/6] Creating directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $tenantDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $scriptDir "tests") -Force | Out-Null

# Step 2: Process template
Write-Host "[2/6] Processing template..." -ForegroundColor Yellow
$templateArgs = @(
    (Join-Path $scriptDir "tools" "process_template.py"),
    $Template,
    $faqsPath,
    "--business_name=$BusinessName",
    "--service_area=$ServiceArea",
    "--base_price=$BasePrice",
    "--phone=$Phone",
    "--email=$Email"
)
& $pythonExe @templateArgs
if ($LASTEXITCODE -ne 0) { throw "Template processing failed" }

# Step 3: Expand variants (deterministic)
Write-Host "[3/6] Expanding variants (deterministic)..." -ForegroundColor Yellow
$expandScript = Join-Path $scriptDir "tools" "expand_variants.py"
if (Test-Path $expandScript) {
    & $pythonExe $expandScript --input $faqsPath --output $variantsPath --overwrite
} else {
    Copy-Item $faqsPath $variantsPath
}

# Step 4: LLM variant generation (optional)
if (-not $SkipLLMVariants) {
    Write-Host "[4/6] Generating LLM variants..." -ForegroundColor Yellow
    $llmScript = Join-Path $scriptDir "tools" "generate_variants_llm.py"
    if (Test-Path $llmScript) {
        & $pythonExe $llmScript $variantsPath --max-per-faq=50
    } else {
        Write-Host "  Skipping (script not found)" -ForegroundColor Gray
    }
} else {
    Write-Host "[4/6] Skipping LLM variants (--SkipLLMVariants)" -ForegroundColor Gray
}

# Step 5: Upload staged
Write-Host "[5/6] Uploading staged FAQs..." -ForegroundColor Yellow
$uploadBody = Get-Content $variantsPath -Raw
try {
    $result = Invoke-RestMethod -Uri "$renderBaseUrl/admin/api/tenant/$TenantId/faqs/staged" `
        -Method PUT -Headers $headers -Body $uploadBody -TimeoutSec 120
    Write-Host "  ✅ Staged upload complete" -ForegroundColor Green
} catch {
    throw "Staged upload failed: $($_.Exception.Message)"
}

# Step 6: Promote (unless skipped)
if (-not $SkipPromote) {
    Write-Host "[6/6] Promoting to live..." -ForegroundColor Yellow
    try {
        $promoteResult = Invoke-RestMethod -Uri "$renderBaseUrl/admin/api/tenant/$TenantId/promote" `
            -Method POST -Headers $headers -TimeoutSec 120
        
        if ($promoteResult.success -or $promoteResult.status -eq "promoted") {
            Write-Host "  ✅ Promoted to live!" -ForegroundColor Green
        } else {
            Write-Host "  ⚠️ Promote returned: $($promoteResult | ConvertTo-Json -Compress)" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "  ❌ Promote failed: $($_.Exception.Message)" -ForegroundColor Red
    }
} else {
    Write-Host "[6/6] Skipping promote (--SkipPromote)" -ForegroundColor Gray
}

# Generate install snippet
Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  INSTALL SNIPPET" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

$snippet = @"
<script 
  src="https://mm-client1-creator-ui.pages.dev/widget.js"
  data-greeting="Hi! How can I help you today?"
  data-header="$BusinessName"
  data-color="$PrimaryColor"
></script>
"@

Write-Host $snippet -ForegroundColor White

Write-Host "`n✅ Onboarding complete for $TenantId" -ForegroundColor Green
Write-Host "Next: Add domain(s) via Admin UI, then test the widget." -ForegroundColor Cyan

