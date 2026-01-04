# New Tenant Onboarding Script
# 
# This script is the mandatory onboarding flow for new tenants.
# It always enables variant expansion and enforces benchmark gates.
# Idempotent: can be run multiple times safely.

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [Parameter(Mandatory=$true)][string]$AdminBase,
  [Parameter(Mandatory=$true)][string]$PublicBase,
  [Parameter(Mandatory=$true)][string]$Origin
)

$ErrorActionPreference = "Stop"

# ---- Resolve repo root reliably ----
$root = $PSScriptRoot
if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }

# ---- Paths ----
$benchScript = Join-Path (Join-Path $root "tools") "bench_messy_inputs.py"
$benchCasesFile = Join-Path (Join-Path $root "tools") "bench_cases.json"
$tenantDir = Join-Path $root "tenants" $TenantId
$faqsSource = Join-Path $tenantDir "faqs.json"
$expandedPath = Join-Path $tenantDir "faqs_expanded.json"
$faqFile = Join-Path $tenantDir "faqs_variants.json"
$expandScript = Join-Path (Join-Path $root "tools") "expand_variants.py"
$profilePath = Join-Path $tenantDir "variant_profile.json"
$corePath = Join-Path $root "variant_library_core.json"
$venvActivate = Join-Path $root ".venv" "Scripts" "Activate.ps1"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  NEW TENANT ONBOARDING" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Tenant: $TenantId" -ForegroundColor Yellow
Write-Host ""

# ---- Preconditions ----
if (-not (Test-Path $faqsSource)) { throw "Missing tenant faqs.json: $faqsSource" }
if (-not (Test-Path $benchScript)) { throw "Missing bench_messy_inputs.py at: $benchScript" }
if (-not (Test-Path $benchCasesFile)) { throw "Missing bench_cases.json at: $benchCasesFile" }
if (-not (Test-Path $expandScript)) { throw "Missing expand_variants.py at: $expandScript" }
if (-not (Test-Path $profilePath)) { throw "Missing variant_profile.json at: $profilePath" }
if (-not (Test-Path $corePath)) { throw "Missing variant_library_core.json at: $corePath" }

# Check benchmark cases count
$benchCases = Get-Content $benchCasesFile -Raw | ConvertFrom-Json
if ($benchCases.Count -lt 15) {
    Write-Host "⚠️  Warning: Only $($benchCases.Count) benchmark cases found. Need at least 15." -ForegroundColor Yellow
}

# ---- Function: Get Admin Token ----
function Get-AdminToken {
    $envFile = Join-Path $root ".env"
    if (-not (Test-Path $envFile)) { throw "Missing .env at repo root: $envFile" }
    $line = Get-Content $envFile | Where-Object { $_ -match '^\s*ADMIN_TOKEN\s*=' } | Select-Object -First 1
    if (-not $line) { throw "ADMIN_TOKEN not found in .env" }
    return ($line -replace '^\s*ADMIN_TOKEN\s*=\s*', '').Trim().Trim('"').Trim("'")
}

# ---- Function: Run Benchmark Gate ----
function Test-BenchmarkGate {
    param(
        [string]$BaseUrl,
        [string]$TenantId,
        [string]$OutputDir
    )
    
    Write-Host "Running benchmark gate..." -ForegroundColor Cyan
    
    # Run benchmark
    $benchOutput = python "$benchScript" --base-url "$BaseUrl" --tenant-id "$TenantId" --output-dir "$OutputDir" 2>&1 | Out-String
    
    Write-Host $benchOutput
    
    # Parse output to extract summary
    $hitRate = 0
    $clarifyRate = 0
    $fallbackRate = 0
    $totalCases = 0
    
    if ($benchOutput -match "Total Cases: (\d+)") {
        $totalCases = [int]$Matches[1]
    }
    if ($benchOutput -match "FAQ Hits: \d+ \(([\d.]+)%\)") {
        $hitRate = [double]$Matches[1]
    }
    if ($benchOutput -match "Clarifies: \d+ \(([\d.]+)%\)") {
        $clarifyRate = [double]$Matches[1]
    }
    if ($benchOutput -match "Fallbacks: \d+ \(([\d.]+)%\)") {
        $fallbackRate = [double]$Matches[1]
    }
    
    # Find the latest results JSON file
    $resultsFiles = Get-ChildItem $OutputDir -Filter "bench_results_*.json" | Sort-Object LastWriteTime -Descending
    if ($resultsFiles.Count -eq 0) {
        throw "No benchmark results file found"
    }
    
    $latestResults = Get-Content $resultsFiles[0].FullName -Raw | ConvertFrom-Json
    $summary = $latestResults.summary
    $results = $latestResults.results
    
    # Calculate non-junk fallback rate
    $nonJunkResults = $results | Where-Object { $_.category -ne "junk" }
    $nonJunkFallbacks = ($nonJunkResults | Where-Object { $_.x_debug_branch -in @("fact_miss", "general_fallback") }).Count
    $nonJunkTotal = $nonJunkResults.Count
    $nonJunkFallbackRate = if ($nonJunkTotal -gt 0) { ($nonJunkFallbacks / $nonJunkTotal) * 100.0 } else { 0.0 }
    
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  BENCHMARK GATE RESULTS" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Total Cases: $totalCases" -ForegroundColor White
    Write-Host "FAQ Hit Rate: $hitRate% (required: >= 70%)" -ForegroundColor $(if ($hitRate -ge 70) { "Green" } else { "Red" })
    Write-Host "Non-Junk Fallback Rate: $([math]::Round($nonJunkFallbackRate, 1))% (required: == 0%)" -ForegroundColor $(if ($nonJunkFallbackRate -eq 0) { "Green" } else { "Red" })
    Write-Host "Clarify Rate: $clarifyRate% (allowed)" -ForegroundColor White
    
    # Show worst misses if any
    if ($summary.worst_misses -and $summary.worst_misses.Count -gt 0) {
        Write-Host ""
        Write-Host "Worst misses:" -ForegroundColor Yellow
        foreach ($miss in $summary.worst_misses) {
            $score = $miss.x_retrieval_score
            $input = $miss.input.Substring(0, [Math]::Min(50, $miss.input.Length))
            Write-Host "  - Score: $score | Input: $input..." -ForegroundColor Gray
        }
    }
    
    Write-Host ""
    
    # Check thresholds
    $passed = $true
    $failures = @()
    
    if ($totalCases -lt 15) {
        $passed = $false
        $failures += "Insufficient test cases: $totalCases (required: >= 15)"
    }
    
    if ($hitRate -lt 70) {
        $passed = $false
        $failures += "FAQ hit rate too low: $hitRate% (required: >= 70%)"
    }
    
    if ($nonJunkFallbackRate -gt 0) {
        $passed = $false
        $failures += "Non-junk fallback rate too high: $([math]::Round($nonJunkFallbackRate, 1))% (required: == 0%)"
    }
    
    if (-not $passed) {
        Write-Host "❌ BENCHMARK GATE FAILED" -ForegroundColor Red
        Write-Host ""
        Write-Host "Failures:" -ForegroundColor Red
        foreach ($failure in $failures) {
            Write-Host "  - $failure" -ForegroundColor Red
        }
        Write-Host ""
        Write-Host "Fix issues and re-run onboarding." -ForegroundColor Yellow
        return $false
    }
    
    Write-Host "✅ BENCHMARK GATE PASSED" -ForegroundColor Green
    return $true
}

# ---- Step 0: Run pytest ----
Write-Host "[0/4] Running pytest..." -ForegroundColor Yellow
Write-Host ""

# Activate venv if present
if (Test-Path $venvActivate) {
    Write-Host "Activating virtual environment..." -ForegroundColor Gray
    & $venvActivate
}

# Check if pytest is installed, install if missing
$pytestCheck = python -m pytest --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "pytest not found, installing..." -ForegroundColor Yellow
    python -m pip install -q pytest
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install pytest"
    }
}

# Run pytest
Write-Host "Running pytest..." -ForegroundColor Cyan
$pytestOutput = python -m pytest -q 2>&1 | Out-String
Write-Host $pytestOutput

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ pytest failed!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Fix test failures before proceeding with onboarding." -ForegroundColor Yellow
    exit 1
}

# Extract summary line
if ($pytestOutput -match "(\d+) (passed|failed|error)") {
    $pytestSummary = $Matches[0]
    Write-Host "✅ pytest: $pytestSummary" -ForegroundColor Green
} else {
    Write-Host "✅ pytest: passed" -ForegroundColor Green
}

Write-Host ""

# ---- Step 1: Expand Variants ----
Write-Host "[1/4] Expanding variants..." -ForegroundColor Yellow
Write-Host ""

& python "$expandScript" --input "$faqsSource" --output "$expandedPath" --overwrite
if ($LASTEXITCODE -ne 0) { throw "expand_variants.py failed" }

Write-Host "✅ Variant expansion completed" -ForegroundColor Green
Write-Host ""

# ---- Step 2: Apply Variant Library and Patches ----
Write-Host "[2/4] Applying variant library and patches..." -ForegroundColor Yellow
Write-Host ""

# Copy expanded FAQs to variants file
Copy-Item $expandedPath $faqFile -Force

# Apply variant library
Write-Host "Applying variant library..." -ForegroundColor Gray
& python (Join-Path $root "apply_variant_library.py") --infile $faqFile --outfile $faqFile --core $corePath --profile $profilePath
if ($LASTEXITCODE -ne 0) { throw "apply_variant_library.py failed" }

# Patch must-hit variants
Write-Host "Patching must-hit variants..." -ForegroundColor Gray
& python (Join-Path $root "patch_must_variants.py") --faqfile $faqFile --profile $profilePath
if ($LASTEXITCODE -ne 0) { throw "patch_must_variants.py failed" }

# Patch parking variants
Write-Host "Patching parking variants..." -ForegroundColor Gray
& python (Join-Path $root "patch_parking_variants.py") -TenantId $TenantId
if ($LASTEXITCODE -ne 0) { throw "patch_parking_variants.py failed" }

Write-Host "✅ Variant processing completed" -ForegroundColor Green
Write-Host ""

# ---- Step 3: Upload to Staging and Promote ----
Write-Host "[3/4] Uploading to staging and promoting..." -ForegroundColor Yellow
Write-Host ""

$token = Get-AdminToken
$stagedUri = ($AdminBase.TrimEnd("/") + "/admin/api/tenant/$TenantId/faqs/staged")
$promoteUri = ($AdminBase.TrimEnd("/") + "/admin/api/tenant/$TenantId/promote")

# Load FAQs JSON
$faqsJson = Get-Content $faqFile -Raw -Encoding UTF8
$faqsData = $faqsJson | ConvertFrom-Json

# Upload to staging
Write-Host "Uploading to staging..." -ForegroundColor Gray
try {
    $stagedResp = Invoke-RestMethod -Uri $stagedUri `
        -Method Put `
        -Headers @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" } `
        -Body $faqsJson `
        -ErrorAction Stop
    
    Write-Host "✅ Staged $($stagedResp.staged_count) FAQs" -ForegroundColor Green
} catch {
    Write-Host "❌ Staging upload failed: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response) {
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $body = $reader.ReadToEnd()
        Write-Host "Response: $body" -ForegroundColor Yellow
    }
    throw
}

# Small delay before promote
Start-Sleep -Seconds 2

# Promote staged FAQs
Write-Host "Promoting staged FAQs..." -ForegroundColor Gray
try {
    $promoteResp = Invoke-RestMethod -Uri $promoteUri `
        -Method Post `
        -Headers @{ Authorization = "Bearer $token" } `
        -ErrorAction Stop
    
    if ($promoteResp.status -eq "success") {
        Write-Host "✅ Promote: SUCCESS" -ForegroundColor Green
        Write-Host "   Message: $($promoteResp.message)" -ForegroundColor Gray
        if ($promoteResp.suite_result) {
            $suitePassed = $promoteResp.suite_result.passed
            Write-Host "   Suite: $(if ($suitePassed) { 'PASSED' } else { 'FAILED' })" -ForegroundColor $(if ($suitePassed) { "Green" } else { "Red" })
        }
    } else {
        Write-Host "❌ Promote: FAILED" -ForegroundColor Red
        Write-Host "   Message: $($promoteResp.message)" -ForegroundColor Yellow
        if ($promoteResp.first_failure) {
            Write-Host "   First failure:" -ForegroundColor Red
            $failure = $promoteResp.first_failure
            if ($failure.name) { Write-Host "     Name: $($failure.name)" -ForegroundColor Yellow }
            if ($failure.question) { Write-Host "     Question: $($failure.question)" -ForegroundColor Yellow }
            if ($failure.fails) { Write-Host "     Failures: $($failure.fails -join ', ')" -ForegroundColor Red }
        }
        throw "Promote failed: $($promoteResp.message)"
    }
} catch {
    Write-Host "❌ Promote failed: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.Exception.Response) {
        $stream = $_.Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        $body = $reader.ReadToEnd()
        Write-Host "Response: $body" -ForegroundColor Yellow
    }
    throw
}

Write-Host ""

# Small delay to ensure server is ready
Start-Sleep -Seconds 5

# ---- Step 4: Run Benchmark Gate ----
Write-Host "[4/4] Running benchmark gate..." -ForegroundColor Yellow
Write-Host ""

$gatePassed = Test-BenchmarkGate -BaseUrl $PublicBase -TenantId $TenantId -OutputDir (Join-Path $root "tools")

if (-not $gatePassed) {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  ONBOARDING FAILED" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "The benchmark gate did not pass. Please:" -ForegroundColor Yellow
    Write-Host "  1. Review the benchmark results above" -ForegroundColor Yellow
    Write-Host "  2. Add more FAQ variants or improve FAQ coverage" -ForegroundColor Yellow
    Write-Host "  3. Re-run: .\new_tenant_onboard.ps1 ..." -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ---- Success ----
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  ONBOARDING COMPLETE" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "✅ pytest: Passed" -ForegroundColor Green
Write-Host "✅ Variant expansion: Enabled" -ForegroundColor Green
Write-Host "✅ Staging upload: Success" -ForegroundColor Green
Write-Host "✅ Promote: Success" -ForegroundColor Green
Write-Host "✅ Benchmark gate: Passed" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Verify readiness: GET /admin/api/tenant/$TenantId/readiness" -ForegroundColor White
Write-Host "  2. Generate install snippet from Admin UI" -ForegroundColor White
Write-Host "  3. Send snippet to customer for installation" -ForegroundColor White
Write-Host ""
