[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [Parameter(Mandatory=$false)][string]$BusinessName = "",
  [Parameter(Mandatory=$false)][string]$PrimaryColor = "#2563eb",
  [Parameter(Mandatory=$false)][string]$Greeting = "Hi! How can I help you today?",
  [Parameter(Mandatory=$false)][switch]$PromoteOnly,
  [Parameter(Mandatory=$false)][switch]$SkipPromote,
  [Parameter(Mandatory=$false)][switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Paths
$scriptDir = $PSScriptRoot
$tenantDir = Join-Path $scriptDir "tenants" $TenantId
$faqsPath = Join-Path $tenantDir "faqs.json"
$variantsPath = Join-Path $tenantDir "faqs_variants.json"
$testsPath = Join-Path $scriptDir "tests" "$TenantId.json"

# Load admin token from .env
$envPath = Join-Path $scriptDir ".env"
if (-not (Test-Path $envPath)) {
    Write-Error "Missing .env file at $envPath"
    exit 1
}
$adminToken = (Get-Content $envPath | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
if (-not $adminToken) {
    Write-Error "ADMIN_TOKEN not found in .env"
    exit 1
}

# API URLs - use Render direct for admin (Cloudflare blocks admin routes)
$renderBaseUrl = "https://motionmade-fastapi.onrender.com"
$headers = @{
    "Authorization" = "Bearer $adminToken"
    "Content-Type" = "application/json"
}

function Write-Step {
    param([string]$Message)
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  ✅ $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  ⚠️ $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  ❌ $Message" -ForegroundColor Red
}

# ========================================
# PROMOTE-ONLY MODE
# ========================================
if ($PromoteOnly) {
    Write-Step "PROMOTE-ONLY MODE for $TenantId"
    
    try {
        $promoteResult = Invoke-RestMethod -Uri "$renderBaseUrl/admin/api/tenant/$TenantId/promote" `
            -Method POST -Headers $headers -TimeoutSec 120
        
        if ($promoteResult.success -or $promoteResult.status -eq "promoted") {
            Write-Ok "Promote succeeded"
            Write-Host ($promoteResult | ConvertTo-Json -Depth 5)
            exit 0
        } else {
            Write-Fail "Promote failed"
            Write-Host ($promoteResult | ConvertTo-Json -Depth 5)
            exit 1
        }
    } catch {
        Write-Fail "Promote request failed: $($_.Exception.Message)"
        exit 1
    }
}

# ========================================
# FULL ONBOARDING
# ========================================
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  ONBOARDING TENANT: $TenantId" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# --- Step 1: Create directories ---
Write-Step "1. Creating directories"

if (-not (Test-Path $tenantDir)) {
    New-Item -ItemType Directory -Path $tenantDir -Force | Out-Null
    Write-Ok "Created $tenantDir"
} else {
    Write-Warn "Directory already exists: $tenantDir"
}

$testsDir = Join-Path $scriptDir "tests"
if (-not (Test-Path $testsDir)) {
    New-Item -ItemType Directory -Path $testsDir -Force | Out-Null
}

# --- Step 2: Check for FAQs ---
Write-Step "2. Checking FAQs"

if (-not (Test-Path $faqsPath)) {
    Write-Warn "No faqs.json found at $faqsPath"
    Write-Host "  Creating starter template..." -ForegroundColor Gray
    
    $starterFaqs = @(
        @{
            question = "Pricing and quotes"
            answer = "Our pricing depends on the service type and your specific needs. Could you tell me what service you're interested in? I'll give you accurate pricing information."
            variants = @("prices", "pricing", "how much", "cost", "quote", "rates", "what do you charge", "ur prices", "ur prices pls")
        },
        @{
            question = "Service area"
            answer = "Please let me know your suburb and I can confirm if we cover your location."
            variants = @("where do you service", "do you come to", "areas", "suburbs", "locations", "wat areas", "wat areas do u cover")
        },
        @{
            question = "Booking and availability"
            answer = "We typically have availability within a few days. Would you like to book a time?"
            variants = @("book", "booking", "availability", "schedule", "appointment", "next available", "can u come", "can u come today")
        }
    )
    
    $starterFaqs | ConvertTo-Json -Depth 10 | Set-Content -Path $faqsPath -Encoding UTF8
    Write-Ok "Created starter faqs.json - EDIT THIS with real business FAQs"
} else {
    $faqCount = (Get-Content $faqsPath | ConvertFrom-Json).Count
    Write-Ok "Found $faqCount FAQs in faqs.json"
}

# --- Step 3: Expand variants ---
Write-Step "3. Expanding variants"

$expandScript = Join-Path $scriptDir "tools" "expand_variants.py"
if (Test-Path $expandScript) {
    $pythonExe = Join-Path $scriptDir ".venv" "Scripts" "python.exe"
    if (-not (Test-Path $pythonExe)) {
        $pythonExe = "python"
    }
    
    # Expand and save to faqs_variants.json
    & $pythonExe $expandScript --input $faqsPath --output $variantsPath --overwrite
    
    if (Test-Path $variantsPath) {
        $variantFaqs = Get-Content $variantsPath | ConvertFrom-Json
        $totalVariants = ($variantFaqs | ForEach-Object { $_.variants.Count } | Measure-Object -Sum).Sum
        Write-Ok "Expanded to $totalVariants total variants across $($variantFaqs.Count) FAQs"
    } else {
        Write-Warn "Variant expansion didn't create output file"
        Copy-Item $faqsPath $variantsPath
    }
} else {
    Write-Warn "expand_variants.py not found at $expandScript - copying faqs.json as-is"
    Copy-Item $faqsPath $variantsPath -Force
}

# --- Step 4: Create test suite if missing ---
Write-Step "4. Checking test suite"

if (-not (Test-Path $testsPath)) {
    Write-Warn "No test suite found at $testsPath"
    Write-Host "  Creating starter test suite..." -ForegroundColor Gray
    
    $starterTests = @{
        tests = @(
            @{
                name = "Pricing query (clean)"
                question = "how much do you charge"
                expect_faq_hit = $true
            },
            @{
                name = "Pricing query (messy)"
                question = "ur prices pls"
                expect_faq_hit = $true
            },
            @{
                name = "Service area (messy)"
                question = "wat areas do u cover"
                expect_faq_hit = $true
            },
            @{
                name = "Unknown capability"
                question = "do you do brain surgery"
                expect_faq_hit = $false
            },
            @{
                name = "Junk input"
                question = "???"
                expect_debug_branch = "clarify"
            }
        )
    }
    
    $starterTests | ConvertTo-Json -Depth 10 | Set-Content -Path $testsPath -Encoding UTF8
    Write-Ok "Created starter test suite - EDIT THIS to match your FAQs"
} else {
    $testCount = (Get-Content $testsPath | ConvertFrom-Json).tests.Count
    Write-Ok "Found $testCount tests in test suite"
}

# --- Step 5: Upload staged FAQs ---
Write-Step "5. Uploading staged FAQs"

$uploadBody = Get-Content $variantsPath -Raw

try {
    $uploadResult = Invoke-RestMethod -Uri "$renderBaseUrl/admin/api/tenant/$TenantId/faqs/staged" `
        -Method PUT -Headers $headers -Body $uploadBody -TimeoutSec 60
    
    Write-Ok "Staged upload complete"
    Write-Host "  Response: $($uploadResult | ConvertTo-Json -Compress)" -ForegroundColor Gray
} catch {
    Write-Fail "Staged upload failed: $($_.Exception.Message)"
    if (-not $Force) { exit 1 }
}

# --- Step 6: Promote (runs suite internally) ---
if ($SkipPromote) {
    Write-Step "6. Skipping promote (--SkipPromote flag)"
    Write-Warn "FAQs are staged but NOT live. Run with -PromoteOnly to promote."
} else {
    Write-Step "6. Promoting (runs test suite)"
    
    try {
        $promoteResult = Invoke-RestMethod -Uri "$renderBaseUrl/admin/api/tenant/$TenantId/promote" `
            -Method POST -Headers $headers -TimeoutSec 120
        
        if ($promoteResult.success -or $promoteResult.status -eq "promoted") {
            Write-Ok "Promote succeeded - FAQs are now LIVE"
            
            if ($promoteResult.suite_result) {
                Write-Host "  Suite: $($promoteResult.suite_result.passed)/$($promoteResult.suite_result.total) tests passed" -ForegroundColor Gray
            }
        } else {
            Write-Fail "Promote failed - FAQs remain staged"
            Write-Host ($promoteResult | ConvertTo-Json -Depth 5) -ForegroundColor Yellow
            
            if ($promoteResult.first_failure) {
                Write-Host "`n  First failure:" -ForegroundColor Yellow
                Write-Host "    Test: $($promoteResult.first_failure.name)" -ForegroundColor Yellow
                Write-Host "    Expected: $($promoteResult.first_failure.expected)" -ForegroundColor Yellow
                Write-Host "    Got: $($promoteResult.first_failure.actual)" -ForegroundColor Yellow
            }
            
            if (-not $Force) { exit 1 }
        }
    } catch {
        Write-Fail "Promote request failed: $($_.Exception.Message)"
        if (-not $Force) { exit 1 }
    }
}

# --- Step 7: Generate install snippet ---
Write-Step "7. Install snippet"

$businessNameDisplay = if ($BusinessName) { $BusinessName } else { $TenantId }

$snippet = @"
<script 
  src="https://mm-client1-creator-ui.pages.dev/widget.js"
  data-greeting="$Greeting"
  data-header="$businessNameDisplay Support"
  data-color="$PrimaryColor"
></script>
"@

Write-Host "`nAdd this to the customer's website (before </body>):" -ForegroundColor Yellow
Write-Host $snippet -ForegroundColor White

# --- Step 8: Readiness check ---
Write-Step "8. Readiness check"

try {
    $readiness = Invoke-RestMethod -Uri "$renderBaseUrl/admin/api/tenant/$TenantId/readiness" `
        -Method GET -Headers $headers -TimeoutSec 30
    
    foreach ($check in $readiness.checks) {
        if ($check.passed) {
            Write-Ok "$($check.check): $($check.message)"
        } else {
            Write-Warn "$($check.check): $($check.message)"
        }
    }
    
    if ($readiness.ready) {
        Write-Host "`n🚀 TENANT IS READY FOR LAUNCH" -ForegroundColor Green
    } else {
        Write-Host "`n⚠️ TENANT NOT READY - address warnings above" -ForegroundColor Yellow
    }
} catch {
    Write-Warn "Could not check readiness: $($_.Exception.Message)"
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  ONBOARDING COMPLETE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
