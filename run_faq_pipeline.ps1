[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [Parameter(Mandatory=$true)][string]$AdminBase,            # where /api/v2/admin/tenant/{id}/faqs lives
  [Parameter(Mandatory=$true)][string]$PublicBase,           # Worker base (NOT FastAPI)
  [Parameter(Mandatory=$true)][string]$Origin,               # UI origin to test through widget

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

$faqsSource  = Join-Path $tenantDir "faqs.json"                  # canonical input
$faqFile     = Join-Path $tenantDir "faqs_variants.json"         # generated/upload artifact
$lastGood    = Join-Path $tenantDir "last_good_faqs_variants.json"
$backupsDir  = Join-Path $tenantDir "backups"

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

  $uri = ($AdminBase.TrimEnd("/") + "/api/v2/admin/tenant/$TenantId/faqs")
  $resp = Invoke-WebRequest -UseBasicParsing `
    -Uri $uri `
    -Method Put `
    -Headers @{ Authorization = "Bearer $Token" } `
    -ContentType "application/json" `
    -InFile $Path `
    -TimeoutSec $TimeoutSec

  if ($resp.StatusCode -ne 200) { throw "Upload failed HTTP $($resp.StatusCode)" }
  Write-Host "Upload OK (HTTP 200) -> $uri" -ForegroundColor Green
}

# ---- Preconditions ----
if (-not (Test-Path $tenantDir))   { throw "Missing tenant dir: $tenantDir" }
if (-not (Test-Path $profilePath)) { throw "Missing tenant profile: $profilePath" }
if (-not (Test-Path $corePath))    { throw "Missing core library: $corePath" }

if (-not (Test-Path (Join-Path $root "apply_variant_library.py"))) { throw "Missing apply_variant_library.py at repo root" }
if (-not (Test-Path (Join-Path $root "patch_must_variants.py")))   { throw "Missing patch_must_variants.py at repo root" }
if (-not (Test-Path (Join-Path $root "patch_parking_variants.py"))) { throw "Missing patch_parking_variants.py at repo root" }

if (-not (Test-Path $faqsSource)) { throw "Missing tenant faqs.json: $faqsSource" }

# Ensure backups dir exists
if (-not (Test-Path $backupsDir)) { New-Item -ItemType Directory -Path $backupsDir | Out-Null }

# Always rebuild faqs_variants.json from canonical faqs.json (no surprises)
Copy-Item $faqsSource $faqFile -Force
Write-Host "Rebuilt faqs_variants.json from faqs.json" -ForegroundColor Yellow

# Backup this rebuilt artifact
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$bak = Join-Path $backupsDir ("faqs_variants.$ts.json")
Copy-Item $faqFile $bak -Force
Write-Host "Backup saved: $bak" -ForegroundColor DarkGray

Assert-UnderTenant $faqFile

try {
  # 1) Apply variant library
  Write-Host "Applying variant library (core + tenant profile)..." -ForegroundColor Cyan
  python (Join-Path $root "apply_variant_library.py") --infile $faqFile --outfile $faqFile --core $corePath --profile $profilePath
  if ($LASTEXITCODE -ne 0) { throw "apply_variant_library.py failed" }

  # 2) Patch must-hit variants
  Write-Host "Patching must-hit variants..." -ForegroundColor Cyan
  python (Join-Path $root "patch_must_variants.py") --faqfile $faqFile --profile $profilePath
  if ($LASTEXITCODE -ne 0) { throw "patch_must_variants.py failed" }

  # 3) Patch parking variants
  Write-Host "Patching parking variants..." -ForegroundColor Cyan
  python (Join-Path $root "patch_parking_variants.py") -TenantId $TenantId
  if ($LASTEXITCODE -ne 0) { throw "patch_parking_variants.py failed" }

  # 4) Upload
  Write-Host "Uploading FAQs (ADMIN)..." -ForegroundColor Cyan
  $token = Get-AdminToken
  Upload-Faqs -Path $faqFile -Token $token | Out-Null

  # 5) Run widget suite explicitly and trust its exit code
  Write-Host "Running suite (PUBLIC widget)..." -ForegroundColor Cyan
  $suite = Join-Path $root "run_suite_widget.ps1"
  if (-not (Test-Path $suite)) { throw "Missing run_suite_widget.ps1 at repo root: $suite" }

  & powershell -ExecutionPolicy Bypass -NoProfile -File $suite `
    -TenantId $TenantId `
    -Base $PublicBase `
    -Origin $Origin

  $code = $LASTEXITCODE
  if ($code -ne 0) { throw "Suite failed" }

  # Promote last_good
  Copy-Item $faqFile $lastGood -Force
  Write-Host "✅ Suite PASS. Promoted to last_good." -ForegroundColor Green
}
catch {
  Write-Host "❌ Pipeline failed: $($_.Exception.Message)" -ForegroundColor Red

  if (Test-Path $lastGood) {
    Write-Host "Rolling back by re-uploading last_good (ADMIN)..." -ForegroundColor Yellow
    $token = Get-AdminToken
    Upload-Faqs -Path $lastGood -Token $token | Out-Null
    Copy-Item $lastGood $faqFile -Force
    Write-Host "Rollback upload OK." -ForegroundColor Green
  } else {
    Write-Host "No last_good found to rollback." -ForegroundColor Yellow
  }

  throw
}
