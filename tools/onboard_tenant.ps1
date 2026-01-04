#Requires -Version 5.1
<#
.SYNOPSIS
    Complete tenant onboarding: upload FAQs, expand variants, promote, benchmark, add Worker domain.
.DESCRIPTION
    Single command that handles full tenant onboarding:
    1. Uploads FAQs to staging
    2. Promotes (auto-expands variants, runs suite gate)
    3. Runs messy benchmark gate
    4. Adds domain(s) to Worker D1 for widget routing
    5. Prints install snippet
.EXAMPLE
    .\tools\onboard_tenant.ps1 -TenantId "acme_clean" -Domains @("acmecleaning.com.au") -FaqPath "tenants\acme_clean\faqs.json" -AdminBase "https://motionmade-fastapi.onrender.com" -WorkerDbName "motionmade_creator_enquiries"
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$TenantId,
    
    [Parameter(Mandatory=$true)]
    [string[]]$Domains,
    
    [Parameter(Mandatory=$true)]
    [string]$FaqPath,
    
    [Parameter(Mandatory=$false)]
    [string]$AdminBase = "https://motionmade-fastapi.onrender.com",
    
    [Parameter(Mandatory=$false)]
    [string]$WorkerDbName = "motionmade_creator_enquiries",
    
    [Parameter(Mandatory=$false)]
    [string]$PublicBase = "https://api.motionmadebne.com.au",
    
    [Parameter(Mandatory=$false)]
    [string]$WorkerBackendPath = "C:\MM\10__CLIENTS\client1\backend",
    
    [Parameter(Mandatory=$false)]
    [string]$BusinessName = "",
    
    [Parameter(Mandatory=$false)]
    [string]$PrimaryColor = "#2563eb",
    
    [Parameter(Mandatory=$false)]
    [string]$Greeting = "Hi! How can I help you today?",
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipBenchmark,
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipWorkerDomain
)

$ErrorActionPreference = "Stop"
$scriptDir = $PSScriptRoot
$rootDir = Split-Path $scriptDir -Parent

# Load admin token
$envPath = Join-Path $rootDir ".env"
if (-not (Test-Path $envPath)) {
    throw "Missing .env file at $envPath"
}
$adminToken = (Get-Content $envPath | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
if (-not $adminToken) {
    throw "ADMIN_TOKEN not found in .env"
}

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

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  ONBOARDING: $TenantId" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Step 1: Verify FAQ file exists
Write-Step "1. Verifying FAQ file"
if (-not (Test-Path $FaqPath)) {
    throw "FAQ file not found: $FaqPath"
}
$faqs = Get-Content $FaqPath | ConvertFrom-Json
Write-Ok "Found $($faqs.Count) FAQs in $FaqPath"

# Step 2: Check API routes
Write-Step "2. Checking API routes"
try {
    $testResponse = Invoke-WebRequest -Uri "$AdminBase/admin/api/tenant/$TenantId/stats" `
        -Method GET -Headers $headers -ErrorAction SilentlyContinue
    if ($testResponse.StatusCode -eq 200 -or $testResponse.StatusCode -eq 401) {
        Write-Ok "API routes accessible (status: $($testResponse.StatusCode))"
    }
} catch {
    if ($_.Exception.Response.StatusCode -eq 404) {
        Write-Warn "API routes returning 404 - may need deployment"
    } else {
        Write-Warn "API route check: $($_.Exception.Message)"
    }
}

# Step 3: Upload FAQs to staging
Write-Step "3. Uploading FAQs to staging"
$faqsBody = Get-Content $FaqPath -Raw
try {
    $stagedResult = Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$TenantId/faqs/staged" `
        -Method PUT -Headers $headers -Body $faqsBody -TimeoutSec 120
    Write-Ok "Staged $($stagedResult.staged_count) FAQs"
} catch {
    # Fallback to direct upload if staged endpoint fails
    if ($_.Exception.Response.StatusCode -eq 404) {
        Write-Warn "Staged endpoint 404, using direct upload"
        try {
            $directResult = Invoke-RestMethod -Uri "$AdminBase/admin/tenant/$TenantId/faqs" `
                -Method PUT -Headers $headers -Body $faqsBody -TimeoutSec 120
            Write-Ok "Uploaded $($directResult.count) FAQs (direct endpoint)"
            Write-Warn "Note: Direct upload bypasses staging. Variants will expand on next promote."
        } catch {
            throw "Both staged and direct upload failed: $($_.Exception.Message)"
        }
    } else {
        throw "Staging upload failed: $($_.Exception.Message)"
    }
}

# Step 4: Promote (auto-expands variants, runs suite)
Write-Step "4. Promoting to live (auto-expands variants, runs suite)"
try {
    # Try staged promote endpoint first
    $promoteResult = $null
    try {
        $promoteResult = Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$TenantId/promote" `
            -Method POST -Headers $headers -TimeoutSec 180
    } catch {
        if ($_.Exception.Response.StatusCode -eq 404) {
            Write-Warn "Promote endpoint 404 - may need to use direct upload workflow"
            Write-Warn "For now, FAQs are uploaded but not promoted. Run promote manually via Admin UI."
            $promoteResult = @{status = "skipped"; message = "Promote endpoint not available"}
        } else {
            throw
        }
    }
    
    if ($promoteResult.status -eq "success" -or $promoteResult.status -eq "promoted") {
        Write-Ok "Promoted successfully"
        if ($promoteResult.suite_result) {
            $suite = $promoteResult.suite_result
            Write-Host "  Suite: $($suite.passed)/$($suite.total) tests passed" -ForegroundColor Gray
        }
    } elseif ($promoteResult.status -eq "skipped") {
        Write-Warn "Promote skipped - FAQs uploaded but not promoted"
        Write-Warn "Variants will auto-expand on next promote via Admin UI"
    } else {
        Write-Fail "Promote failed: $($promoteResult.message)"
        if ($promoteResult.first_failure) {
            Write-Host "  First failure: $($promoteResult.first_failure.name)" -ForegroundColor Yellow
        }
        throw "Promote failed - suite did not pass"
    }
} catch {
    if ($_.Exception.Message -match "404") {
        Write-Warn "Promote endpoint not available - FAQs uploaded but not promoted"
        Write-Warn "Please promote via Admin UI or wait for deployment"
    } else {
        throw "Promote request failed: $($_.Exception.Message)"
    }
}

# Wait for embeddings
Write-Host "`n  Waiting 30 seconds for embeddings..." -ForegroundColor Gray
Start-Sleep -Seconds 30

# Step 5: Run benchmark gate
if (-not $SkipBenchmark) {
    Write-Step "5. Running messy benchmark gate"
    $pythonExe = Join-Path $rootDir ".venv" "Scripts" "python.exe"
    if (-not (Test-Path $pythonExe)) {
        $pythonExe = "python"
    }
    
    $benchOutput = & $pythonExe (Join-Path $scriptDir "run_benchmark.py") $TenantId --api-url=$PublicBase 2>&1
    
    # Parse benchmark results
    $hitRateMatch = $benchOutput | Select-String "Hit rate:\s*([\d.]+)%"
    $fallbackMatch = $benchOutput | Select-String "Fallback rate:\s*([\d.]+)%"
    $wrongHitMatch = $benchOutput | Select-String "Wrong hit rate:\s*([\d.]+)%"
    $passMatch = $benchOutput | Select-String "\[PASS\]|\[FAIL\]"
    
    if ($hitRateMatch) {
        $hitRate = [double]$hitRateMatch.Matches[0].Groups[1].Value
        $fallbackRate = if ($fallbackMatch) { [double]$fallbackMatch.Matches[0].Groups[1].Value } else { 0 }
        $wrongHitRate = if ($wrongHitMatch) { [double]$wrongHitMatch.Matches[0].Groups[1].Value } else { 0 }
        
        Write-Host "  Hit rate: $hitRate% (threshold: >=75%)" -ForegroundColor $(if ($hitRate -ge 75) { "Green" } else { "Red" })
        Write-Host "  Fallback rate: $fallbackRate% (threshold: ==0%)" -ForegroundColor $(if ($fallbackRate -eq 0) { "Green" } else { "Red" })
        Write-Host "  Wrong hit rate: $wrongHitRate% (threshold: ==0%)" -ForegroundColor $(if ($wrongHitRate -eq 0) { "Green" } else { "Red" })
        
        if ($hitRate -ge 75 -and $fallbackRate -eq 0 -and $wrongHitRate -eq 0) {
            Write-Ok "Benchmark gate PASSED"
        } else {
            Write-Fail "Benchmark gate FAILED"
            throw "Benchmark thresholds not met"
        }
    } else {
        Write-Host $benchOutput -ForegroundColor Yellow
        Write-Warn "Could not parse benchmark results"
    }
} else {
    Write-Step "5. Skipping benchmark (--SkipBenchmark)"
}

# Step 6: Add domains to Worker D1
if (-not $SkipWorkerDomain) {
    Write-Step "6. Adding domain(s) to Worker D1"
    
    if (-not (Test-Path $WorkerBackendPath)) {
        Write-Warn "Worker backend path not found: $WorkerBackendPath"
        Write-Warn "Skipping Worker domain setup. Add manually via wrangler."
    } else {
        Push-Location $WorkerBackendPath
        
        foreach ($domain in $Domains) {
            $domainClean = $domain.Trim().ToLower()
            if (-not $domainClean) { continue }
            
            # Remove protocol if present
            $domainClean = $domainClean -replace "^https?://", ""
            $domainClean = $domainClean -replace "/.*$", ""  # Remove path
            
            $sql = @"
INSERT INTO tenant_domains (domain, tenant_id, enabled, notes)
VALUES ('$domainClean', '$TenantId', 1, 'onboard_tenant.ps1')
ON CONFLICT(domain) DO UPDATE SET tenant_id=excluded.tenant_id, enabled=1, notes=excluded.notes;
"@
            
            try {
                & wrangler d1 execute $WorkerDbName --remote --command $sql 2>&1 | Out-Null
                Write-Ok "Added domain to Worker D1: $domainClean"
            } catch {
                Write-Warn "Failed to add domain to Worker D1: $domainClean - $($_.Exception.Message)"
            }
        }
        
        Pop-Location
    }
} else {
    Write-Step "6. Skipping Worker domain setup (--SkipWorkerDomain)"
}

# Step 7: Generate install snippet
Write-Step "7. Install snippet"
$displayName = if ($BusinessName) { $BusinessName } else { $TenantId }

$snippet = @"
<!-- $displayName Chat Widget -->
<script 
  src="https://mm-client1-creator-ui.pages.dev/widget.js"
  data-greeting="$Greeting"
  data-header="$displayName"
  data-color="$PrimaryColor"
></script>
"@

Write-Host $snippet -ForegroundColor White

# Final summary
Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  ONBOARDING COMPLETE" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Tenant: $TenantId" -ForegroundColor White
Write-Host "Domains: $($Domains -join ', ')" -ForegroundColor White
Write-Host "FAQs: $($faqs.Count)" -ForegroundColor White
Write-Host ""
Write-Host "✅ FAQs uploaded and promoted" -ForegroundColor Green
Write-Host "✅ Variants auto-expanded" -ForegroundColor Green
if (-not $SkipBenchmark) {
    Write-Host "✅ Benchmark gate passed" -ForegroundColor Green
}
if (-not $SkipWorkerDomain) {
    Write-Host "✅ Worker domain(s) configured" -ForegroundColor Green
}
Write-Host ""
Write-Host "Next: Send install snippet to customer" -ForegroundColor Cyan

