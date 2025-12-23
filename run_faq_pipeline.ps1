[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [string]$Base = "https://motionmade-fastapi.onrender.com",
  [int]$TimeoutSec = 600
)

$ErrorActionPreference = "Stop"

# Resolve repo root reliably
$root = $PSScriptRoot
if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }

# Paths
$tenantDir   = Join-Path $root (Join-Path "tenants" $TenantId)
$profilePath = Join-Path $tenantDir "variant_profile.json"
$corePath    = Join-Path $root "variant_library_core.json"
$faqFile     = Join-Path $tenantDir "faqs_variants.json"

# Helpers
function Get-AdminToken {
  $envFile = Join-Path $root ".env"
  $line = Get-Content $envFile | Where-Object { $_ -match '^\s*ADMIN_TOKEN\s*=' } | Select-Object -First 1
  if (-not $line) { throw "ADMIN_TOKEN not found in .env" }
  return ($line -replace '^\s*ADMIN_TOKEN\s*=\s*', '').Trim().Trim('"').Trim("'")
}

function Upload-Faqs {
  param([string]$Path, [string]$Token)
  if (-not (Test-Path $Path)) { throw "FAQ file not found: $Path" }

  $resp = Invoke-WebRequest -UseBasicParsing `
    -Uri "$Base/admin/tenant/$TenantId/faqs" `
    -Method Put `
    -Headers @{ Authorization = "Bearer $Token" } `
    -ContentType "application/json" `
    -InFile $Path `
    -TimeoutSec $TimeoutSec

  if ($resp.StatusCode -ne 200) { throw "Upload failed HTTP $($resp.StatusCode)" }
  Write-Host "Upload OK (HTTP 200)" -ForegroundColor Green
}

function Run-SuiteText {
  $suite = Join-Path $root "run_suite.ps1"
  if (-not (Test-Path $suite)) { throw "Missing run_suite.ps1" }
  return (powershell -ExecutionPolicy Bypass -NoProfile -File $suite -TenantId $TenantId 2>&1 | Out-String)
}

# Preconditions (tests)
if (-not (Test-Path $tenantDir))      { throw "Missing tenant dir: $tenantDir (run .\new_tenant_profile.ps1 first)" }
if (-not (Test-Path $profilePath))    { throw "Missing tenant profile: $profilePath" }
if (-not (Test-Path $corePath))       { throw "Missing core library: $corePath" }
if (-not (Test-Path ".\apply_variant_library.py")) { throw "Missing apply_variant_library.py" }
if (-not (Test-Path ".\patch_must_variants.py"))   { throw "Missing patch_must_variants.py" }
if (-not (Test-Path $faqFile)) {
  throw "Missing tenant FAQ file: $faqFile. Put the tenant's faqs_variants.json here first."
}

# 1) Apply variant library
Write-Host "Applying variant library (core + tenant profile)..." -ForegroundColor Cyan
python .\apply_variant_library.py --infile $faqFile --outfile $faqFile --core $corePath --profile $profilePath
if ($LASTEXITCODE -ne 0) { throw "apply_variant_library.py failed" }

# 2) Patch must-hit variants (profile-driven)
Write-Host "Patching must-hit variants..." -ForegroundColor Cyan
python .\patch_must_variants.py --faqfile $faqFile --profile $profilePath
if ($LASTEXITCODE -ne 0) { throw "patch_must_variants.py failed" }

# 3) Upload
Write-Host "Uploading FAQs..." -ForegroundColor Cyan
$token = Get-AdminToken
Upload-Faqs -Path $faqFile -Token $token | Out-Null

# 4) Run suite
Write-Host "Running suite..." -ForegroundColor Cyan
$out = Run-SuiteText
Write-Host $out

if ($out -match "FAIL:") { throw "Suite failed. Fix profile/tests and rerun." }
Write-Host "✅ Suite PASS. Done." -ForegroundColor Green
