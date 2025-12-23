[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [string]$Base = "https://motionmade-fastapi.onrender.com",
  [string]$Core = ".\variant_library_core.json"
)

$scriptDir = $PSScriptRoot
$repo = Split-Path -Parent $scriptDir

$tenantDir = Join-Path (Join-Path $repo "tenants") $TenantId
$backupDir = Join-Path $tenantDir "backups"

$faqsSrc   = Join-Path $tenantDir "faqs.json"
$profile   = Join-Path $tenantDir "variant_profile.json"
$faqsOut   = Join-Path $tenantDir "faqs_variants.json"
$lastGood  = Join-Path $tenantDir "last_good_faqs_variants.json"
$tests     = Join-Path (Join-Path $repo "tests") "$TenantId.json"

function FailFast([string]$msg) { throw $msg }

function Assert-Json([string]$path, [string]$label) {
  if (-not (Test-Path $path)) { FailFast "Missing ${label}: ${path}" }
  try { Get-Content $path -Raw | ConvertFrom-Json | Out-Null } catch { FailFast "Invalid JSON in ${label}: ${path}" }
}

function Resolve-InTenant([string]$path) {
  $full = [System.IO.Path]::GetFullPath($path)
  $ten  = [System.IO.Path]::GetFullPath($tenantDir)
  if (-not $full.StartsWith($ten, [System.StringComparison]::OrdinalIgnoreCase)) {
    FailFast "Safety violation: path escapes tenant dir. path=$full tenantDir=$ten"
  }
  return $full
}

function Get-AdminToken() {
  $envPath = Join-Path $repo ".env"
  if (-not (Test-Path $envPath)) { FailFast "Missing .env at repo root: $envPath" }
  $line = Get-Content $envPath | Where-Object { $_ -match '^\s*ADMIN_TOKEN\s*=' } | Select-Object -First 1
  if (-not $line) { FailFast "ADMIN_TOKEN not found in .env" }
  return ($line -replace '^\s*ADMIN_TOKEN\s*=\s*', '').Trim().Trim('"').Trim("'")
}

function Upload-Faqs([string]$Path, [string]$Token) {
  $Path = Resolve-InTenant $Path
  if (-not (Test-Path $Path)) { FailFast "FAQ file not found: $Path" }

  $uri = "$Base/admin/tenant/$TenantId/faqs"
  $resp = Invoke-WebRequest -UseBasicParsing -Uri $uri -Method Put `
    -Headers @{ Authorization = "Bearer $Token" } `
    -ContentType "application/json" -InFile $Path -TimeoutSec 600

  if ($resp.StatusCode -ne 200) { FailFast "Upload failed HTTP $($resp.StatusCode)" }

  # best-effort: parse response body
  $body = $null
  try { $body = $resp.Content | ConvertFrom-Json } catch { $body = $null }

  Write-Host "Upload OK (HTTP 200)" -ForegroundColor Green
  if ($body) {
    $t = $body.tenantId
    $c = $body.count
    Write-Host "  server: tenantId=$t count=$c"
  }
}

function Count-Variants([string]$path) {
  $data = Get-Content $path -Raw | ConvertFrom-Json
  $faqCount = @($data).Count
  $variantCount = 0
  $mustCount = 0
  foreach ($f in $data) {
    if ($f.variants) { $variantCount += @($f.variants).Count }
  }
  return [ordered]@{ faq_count=$faqCount; variant_count=$variantCount; must_hit_count=$mustCount }
}

# ---------------------------------------
# Step 0: Validate inputs (fail fast)
# ---------------------------------------
Write-Host "== Tenant: $TenantId ==" -ForegroundColor Cyan
Write-Host "Step 0) Validate inputs..." -ForegroundColor Cyan

if (-not (Test-Path $tenantDir)) { FailFast "Missing tenant folder: $tenantDir" }
New-Item -ItemType Directory -Force $backupDir | Out-Null

Assert-Json $faqsSrc  "tenants/<id>/faqs.json"
Assert-Json $profile  "tenants/<id>/variant_profile.json"
Assert-Json $tests    "tests/<id>.json"
Assert-Json $Core     "variant_library_core.json"

# script existence
if (-not (Test-Path (Join-Path $repo "apply_variant_library.py"))) { FailFast "Missing apply_variant_library.py at repo root" }
if (-not (Test-Path (Join-Path $repo "patch_must_variants.py")))   { FailFast "Missing patch_must_variants.py at repo root" }
if (-not (Test-Path (Join-Path $repo "scripts\run_suite.ps1")))     { FailFast "Missing scripts\run_suite.ps1" }

# ---------------------------------------
# Step 1: Generate variants (deterministic)
# ---------------------------------------
Write-Host "Step 1) Generate variants..." -ForegroundColor Cyan

# start from faqs.json as source truth
Copy-Item $faqsSrc $faqsOut -Force

python (Join-Path $repo "apply_variant_library.py") --infile $faqsOut --outfile $faqsOut --core $Core --profile $profile
if ($LASTEXITCODE -ne 0) { FailFast "apply_variant_library.py failed" }

python (Join-Path $repo "patch_must_variants.py") --faqfile $faqsOut --profile $profile
if ($LASTEXITCODE -ne 0) { FailFast "patch_must_variants.py failed" }

$counts = Count-Variants $faqsOut
Write-Host ("  faq_count={0} variant_count={1}" -f $counts.faq_count, $counts.variant_count) -ForegroundColor DarkGray

# ---------------------------------------
# Step 2: Backup before touching production
# ---------------------------------------
Write-Host "Step 2) Backup before upload..." -ForegroundColor Cyan
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$bak = Join-Path $backupDir ("faqs_variants.{0}.json" -f $ts)
Copy-Item $faqsOut $bak -Force
Write-Host "  backup: $bak" -ForegroundColor DarkGray

# ---------------------------------------
# Step 3: Upload to server
# ---------------------------------------
Write-Host "Step 3) Upload..." -ForegroundColor Cyan
$token = Get-AdminToken
Upload-Faqs -Path $faqsOut -Token $token

# ---------------------------------------
# Step 4: Run tenant test suite automatically
# ---------------------------------------
Write-Host "Step 4) Run suite..." -ForegroundColor Cyan
$p = Join-Path $repo "scripts\run_suite.ps1"
powershell -ExecutionPolicy Bypass -NoProfile -File $p -TenantId $TenantId -Base $Base -TestFile $tests
$suiteExit = $LASTEXITCODE

# ---------------------------------------
# Step 5/6: PASS => commit last_good, FAIL => rollback
# ---------------------------------------
if ($suiteExit -eq 0) {
  Copy-Item $faqsOut $lastGood -Force
  Write-Host ("SUCCESS tenant={0} passed=ALL" -f $TenantId) -ForegroundColor Green
  exit 0
}

Write-Host ("FAILED tenant={0} rolled_back=true" -f $TenantId) -ForegroundColor Red

# rollback source: last_good if exists, else the backup we just made
$rollback = $null
if (Test-Path $lastGood) { $rollback = $lastGood } else { $rollback = $bak }

Write-Host "Rolling back from: $rollback" -ForegroundColor Yellow
Upload-Faqs -Path $rollback -Token $token

FailFast "Suite failed; rollback uploaded."

