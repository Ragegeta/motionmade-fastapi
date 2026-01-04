# Verification script for variant expansion
# Runs baseline and expanded pipelines, then compares benchmarks

param(
    [string]$TenantId = "biz9_real",
    [string]$AdminBase = "https://motionmade-fastapi.onrender.com",
    [string]$PublicBase = "https://api.motionmadebne.com.au",
    [string]$Origin = "https://motionmadebne.com.au"
)

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }

$tenantDir = Join-Path $root "tenants" $TenantId
$benchScript = Join-Path $root "tools" "bench_messy_inputs.py"
$pipelineScript = Join-Path $root "run_faq_pipeline.ps1"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  VARIANT EXPANSION VERIFICATION" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Tenant: $TenantId" -ForegroundColor Yellow
Write-Host ""

# Step 1: Baseline (no expansion)
Write-Host "[1/4] BASELINE: Running pipeline WITHOUT expansion..." -ForegroundColor Yellow
Write-Host ""

& powershell -ExecutionPolicy Bypass -NoProfile -File $pipelineScript `
    -TenantId $TenantId `
    -AdminBase $AdminBase `
    -PublicBase $PublicBase `
    -Origin $Origin

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Baseline pipeline failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[2/4] BASELINE: Running benchmark..." -ForegroundColor Yellow
$baselineResults = & python $benchScript `
    --base-url $PublicBase `
    --tenant-id $TenantId `
    --output-dir (Join-Path $root "tools") `
    2>&1

$baselineOutput = $baselineResults | Out-String
Write-Host $baselineOutput

# Extract baseline summary
$baselineHitRate = if ($baselineOutput -match "FAQ Hits: (\d+) \((\d+\.\d+)%\)") { [double]$Matches[2] } else { 0 }
$baselineClarifyRate = if ($baselineOutput -match "Clarifies: (\d+) \((\d+\.\d+)%\)") { [double]$Matches[2] } else { 0 }
$baselineFallbackRate = if ($baselineOutput -match "Fallbacks: (\d+) \((\d+\.\d+)%\)") { [double]$Matches[2] } else { 0 }

Write-Host ""
Write-Host "Waiting 10 seconds before expanded run..." -ForegroundColor Gray
Start-Sleep -Seconds 10

# Step 2: Expanded
Write-Host ""
Write-Host "[3/4] EXPANDED: Running pipeline WITH expansion..." -ForegroundColor Yellow
Write-Host ""

& powershell -ExecutionPolicy Bypass -NoProfile -File $pipelineScript `
    -TenantId $TenantId `
    -AdminBase $AdminBase `
    -PublicBase $PublicBase `
    -Origin $Origin `
    -ExpandVariants

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Expanded pipeline failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[4/4] EXPANDED: Running benchmark..." -ForegroundColor Yellow
$expandedResults = & python $benchScript `
    --base-url $PublicBase `
    --tenant-id $TenantId `
    --output-dir (Join-Path $root "tools") `
    2>&1

$expandedOutput = $expandedResults | Out-String
Write-Host $expandedOutput

# Extract expanded summary
$expandedHitRate = if ($expandedOutput -match "FAQ Hits: (\d+) \((\d+\.\d+)%\)") { [double]$Matches[2] } else { 0 }
$expandedClarifyRate = if ($expandedOutput -match "Clarifies: (\d+) \((\d+\.\d+)%\)") { [double]$Matches[2] } else { 0 }
$expandedFallbackRate = if ($expandedOutput -match "Fallbacks: (\d+) \((\d+\.\d+)%\)") { [double]$Matches[2] } else { 0 }

# Step 3: Comparison
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  COMPARISON SUMMARY" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Metric              Baseline    Expanded    Delta" -ForegroundColor Yellow
Write-Host "------------------------------------------------" -ForegroundColor Gray
Write-Host ("Hit Rate            {0,6:F1}%    {1,6:F1}%    {2,6:F1}%" -f $baselineHitRate, $expandedHitRate, ($expandedHitRate - $baselineHitRate)) -ForegroundColor $(if ($expandedHitRate -gt $baselineHitRate) { "Green" } else { "White" })
Write-Host ("Clarify Rate        {0,6:F1}%    {1,6:F1}%    {2,6:F1}%" -f $baselineClarifyRate, $expandedClarifyRate, ($expandedClarifyRate - $baselineClarifyRate)) -ForegroundColor White
Write-Host ("Fallback Rate       {0,6:F1}%    {1,6:F1}%    {2,6:F1}%" -f $baselineFallbackRate, $expandedFallbackRate, ($expandedFallbackRate - $baselineFallbackRate)) -ForegroundColor $(if ($expandedFallbackRate -lt $baselineFallbackRate) { "Green" } else { "White" })
Write-Host ""

# Verify THETA unchanged (check retrieval.py)
Write-Host "Verifying THETA threshold unchanged..." -ForegroundColor Yellow
$retrievalFile = Join-Path $root "app" "retrieval.py"
if (Test-Path $retrievalFile) {
    $retrievalContent = Get-Content $retrievalFile -Raw
    if ($retrievalContent -match "THETA\s*=\s*0\.82") {
        Write-Host "✅ THETA = 0.82 (unchanged)" -ForegroundColor Green
    } else {
        Write-Host "⚠️  THETA may have changed - check retrieval.py" -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠️  Could not find retrieval.py to verify THETA" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  VERIFICATION COMPLETE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan


