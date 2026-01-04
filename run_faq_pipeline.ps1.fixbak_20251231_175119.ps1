[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [string]$Base = "https://motionmade-fastapi.onrender.com",
  [int]$TimeoutSec = 600
)

$ErrorActionPreference = "Stop"

# ---- Safety: TenantId shape ----
if ($TenantId -notmatch '^[a-zA-Z0-9_-]+$') {
  throw "Bad TenantId '$TenantId'. Use only letters/numbers/_/-"
}

# ---- Resolve repo root reliably ----
$root = $PSScriptRoot
if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }

# ---- Paths (tenant-scoped) ----
$tenantDir   = Join-Path $root (Join-Path "tenants" $TenantId)
$profilePath = Join-Path $tenantDir "variant_profile.json"
$corePath    = Join-Path $root "variant_library_core.json"

$faqsSource  = Join-Path $tenantDir "faqs.json"                # canonical input
$faqFile     = Join-Path $tenantDir "faqs_variants.json"       # generated/upload artifact
$lastGood    = Join-Path $tenantDir "last_good_faqs_variants.json"
$backupsDir  = Join-Path $tenantDir "backups"

# ---- Helpers ----
function FullPath([string]$p) { return [IO.Path]::GetFullPath($p) }

function Assert-UnderTenant([string]$p) {
  $td = (FullPath $tenantDir).TrimEnd('\') + '\'
  $fp = (FullPath $p)
  if (-not $fp.StartsWith($td, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Path safety violation: '$fp' is not under tenant dir '$td'"
  }
}

function Get-AdminToken {
  $envFile = Join-Path $root ".env"
  if (-not (Test-Path $envFile)) { throw "Missing .env at repo root: $envFile" }
  $line = Get-Content $envFile | Where-Object { $_ -match '^\s*ADMIN_TOKEN\s*=' } | Select-Object -First 1
  if (-not $line) { throw "ADMIN_TOKEN not found in .env" }
  return ($line -replace '^\s*ADMIN_TOKEN\s*=\s*', '').Trim().Trim('"').Trim("'")
}

function Upload-Faqs {
  param([string]$Path, [string]$Token)

  Assert-UnderTenant $Path
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
  if (-not (Test-Path $suite)) { throw "Missing run_suite.ps1 at repo root: $suite" }
  return (powershell -ExecutionPolicy Bypass -NoProfile -File $suite -TenantId $TenantId 2>&1 | Out-String)
}

# ---- Preconditions ----
if (-not (Test-Path $tenantDir))   { throw "Missing tenant dir: $tenantDir (run .\new_tenant_profile.ps1 first)" }
if (-not (Test-Path $profilePath)) { throw "Missing tenant profile: $profilePath" }
if (-not (Test-Path $corePath))    { throw "Missing core library: $corePath" }

if (-not (Test-Path (Join-Path $root "apply_variant_library.py"))) { throw "Missing apply_variant_library.py at repo root" }
if (-not (Test-Path (Join-Path $root "patch_must_variants.py")))   { throw "Missing patch_must_variants.py at repo root" }
python .\patch_parking_variants.py -TenantId $TenantId

if (-not (Test-Path $faqsSource)) { throw "Missing tenant faqs.json (canonical input): $faqsSource" }

# Ensure backups dir exists
if (-not (Test-Path $backupsDir)) { New-Item -ItemType Directory -Path $backupsDir | Out-Null }

# If faqs_variants doesn't exist yet, create it from faqs.json (onboarding = data entry + one command)
if (-not (Test-Path $faqFile)) {
  Copy-Item $faqsSource $faqFile -Force
  Write-Host "Created faqs_variants.json from faqs.json" -ForegroundColor Yellow
} else {
  # Backup current before mutating it
  $ts = Get-Date -Format "yyyyMMdd_HHmmss"
  $bak = Join-Path $backupsDir ("faqs_variants.$ts.json")
  Copy-Item $faqFile $bak -Force
  Write-Host "Backup saved: $bak" -ForegroundColor DarkGray
}

Assert-UnderTenant $faqFile
Assert-UnderTenant $profilePath

# ---- Pipeline ----
try {
  # 1) Apply variant library (core + tenant profile) in-place on faqs_variants.json
  Write-Host "Applying variant library (core + tenant profile)..." -ForegroundColor Cyan
  python (Join-Path $root "apply_variant_library.py") --infile $faqFile --outfile $faqFile --core $corePath --profile $profilePath
  if ($LASTEXITCODE -ne 0) { throw "apply_variant_library.py failed" }

  # 2) Patch must-hit variants (profile-driven)
  Write-Host "Patching must-hit variants..." -ForegroundColor Cyan
  python (Join-Path $root "patch_must_variants.py") --faqfile $faqFile --profile $profilePath
python .\patch_parking_variants.py -TenantId $TenantId
  if ($LASTEXITCODE -ne 0) { throw "patch_must_variants.py failed" }
python .\patch_parking_variants.py -TenantId $TenantId

  # 3) Upload
  Write-Host "Uploading FAQs..." -ForegroundColor Cyan
  $token = Get-AdminToken
  Upload-Faqs -Path $faqFile -Token $token | Out-Null

  # 4) Run suite
  Write-Host "Running suite..." -ForegroundColor Cyan
# WARMUP_GENERATE_CACHE
$warmQs = @(
  "Paid parking",
  "What happens if there is paid parking?",
  "Do you charge for parking if it is metered?"
)
foreach ($q in $warmQs) {
  try {
    $payload = @{ tenantId = $TenantId; customerMessage = $q } | ConvertTo-Json -Compress
    & curl.exe -sS --http1.1 -X POST "https://api.motionmadebne.com.au/api/v2/generate-quote-reply" -H "Content-Type: application/json" --data-raw $payload | Out-Null
  } catch {}
}
# END_WARMUP_GENERATE_CACHE
  $out = Run-SuiteText
  Write-Host $out
if ($out -match "FAIL:") {
  Start-Sleep -Seconds 2
  $out2 = powershell -ExecutionPolicy Bypass -NoProfile -File .\run_suite.ps1 -TenantId $TenantId 2>&1 | Out-String
  if ($out2 -notmatch "FAIL:") { $out = $out2 }
}
if ($out -match "FAIL:") { throw "Suite failed" }
  # Promote last_good on PASS
  Copy-Item $faqFile $lastGood -Force
  Write-Host "✅ Suite PASS. Promoted to last_good." -ForegroundColor Green
}
catch {
  Write-Host "❌ Pipeline failed: $($_.Exception.Message)" -ForegroundColor Red

  # Roll back if possible
  if (Test-Path $lastGood) {
    Write-Host "Rolling back by re-uploading last_good..." -ForegroundColor Yellow
    $token = Get-AdminToken
    Upload-Faqs -Path $lastGood -Token $token | Out-Null
    Copy-Item $lastGood $faqFile -Force
    Write-Host "Rollback upload OK." -ForegroundColor Green
  } else {
    Write-Host "No last_good found to rollback." -ForegroundColor Yellow
  }

  throw
}

