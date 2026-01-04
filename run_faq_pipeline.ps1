[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [Parameter(Mandatory=$true)][string]$AdminBase,            # where /api/v2/admin/tenant/{id}/faqs lives
  [Parameter(Mandatory=$true)][string]$PublicBase,           # Worker base (NOT FastAPI)
  [Parameter(Mandatory=$true)][string]$Origin,               # UI origin to test through widget

  [int]$TimeoutSec = 600,
  [switch]$ExpandVariants = $false                           # Enable automated variant expansion
)

# Allow override of admin base URL via environment variable (for Render direct access)
$ADMIN_BASE_URL = $env:ADMIN_BASE_URL
if ($ADMIN_BASE_URL) {
  Write-Host "Using ADMIN_BASE_URL override: $ADMIN_BASE_URL" -ForegroundColor Cyan
  $AdminBase = $ADMIN_BASE_URL
} else {
  Write-Host "Using AdminBase parameter: $AdminBase" -ForegroundColor Cyan
}

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

function Warm-Up-Render {
  param([string]$BaseUrl)
  
  if (-not $BaseUrl -or $BaseUrl -notlike "*onrender.com*") {
    Write-Host "Skipping warm-up (not Render URL)" -ForegroundColor Gray
    return
  }
  
  Write-Host "Warming up Render service..." -ForegroundColor Cyan
  $warmupUrl = ($BaseUrl.TrimEnd("/") + "/api/health")
  $maxWarmupAttempts = 3
  $warmupDelay = 2
  
  for ($i = 1; $i -le $maxWarmupAttempts; $i++) {
    try {
      $resp = Invoke-WebRequest -Uri $warmupUrl -UseBasicParsing -TimeoutSec 30 -ErrorAction Stop
      Write-Host "  Warm-up ${i}/${maxWarmupAttempts}: HTTP $($resp.StatusCode)" -ForegroundColor Green
      if ($resp.StatusCode -eq 200) {
        Write-Host "  Render service ready" -ForegroundColor Green
        return
      }
    } catch {
      $status = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { "timeout" }
      Write-Host "  Warm-up ${i}/${maxWarmupAttempts}: $status" -ForegroundColor Yellow
    }
    if ($i -lt $maxWarmupAttempts) {
      Start-Sleep -Seconds $warmupDelay
    }
  }
  Write-Host "  Warning: Warm-up incomplete, proceeding anyway" -ForegroundColor Yellow
}

function Upload-Faqs {
  param([string]$Path, [string]$Token)

  Assert-UnderTenant $Path
  if (-not (Test-Path $Path)) { throw "FAQ file not found: $Path" }

  $uri = ($AdminBase.TrimEnd("/") + "/api/v2/admin/tenant/$TenantId/faqs")
  $maxRetries = 2
  $retryCount = 0
  $timeoutSec = 120
  $backoffDelays = @(2, 5)
  
  while ($retryCount -le $maxRetries) {
    try {
      Write-Host "Upload attempt $($retryCount + 1)/$($maxRetries + 1) -> $uri" -ForegroundColor Gray
      $resp = Invoke-WebRequest -UseBasicParsing `
        -Uri $uri `
        -Method Put `
        -Headers @{ Authorization = "Bearer $Token" } `
        -ContentType "application/json" `
        -InFile $Path `
        -TimeoutSec $timeoutSec `
        -ErrorAction Stop

      if ($resp.StatusCode -ne 200) { 
        Write-Host "Upload failed HTTP $($resp.StatusCode)" -ForegroundColor Red
        Write-Host "Response: $($resp.Content)" -ForegroundColor Yellow
        throw "Upload failed HTTP $($resp.StatusCode)" 
      }
      Write-Host "Upload OK (HTTP 200)" -ForegroundColor Green
      Write-Host "Response: $($resp.Content)" -ForegroundColor Green
      return
    } catch {
      $retryCount++
      if ($retryCount -gt $maxRetries) {
        Write-Host "Upload failed after $($maxRetries + 1) attempts" -ForegroundColor Red
        Write-Host "Failing URL: $uri" -ForegroundColor Red
        $status = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { "timeout" }
        Write-Host "Status: $status" -ForegroundColor Red
        if ($_.Exception.Response) {
          try {
            $stream = $_.Exception.Response.GetResponseStream()
            $reader = New-Object System.IO.StreamReader($stream)
            $body = $reader.ReadToEnd()
            Write-Host "Response: $body" -ForegroundColor Yellow
          } catch {}
        }
        throw
      }
      $backoff = $backoffDelays[$retryCount - 1]
      Write-Host "Retrying in $backoff seconds..." -ForegroundColor Yellow
      Start-Sleep -Seconds $backoff
    }
  }
}

# ---- Preconditions ----
if (-not (Test-Path $tenantDir))   { throw "Missing tenant dir: $tenantDir" }
if (-not (Test-Path $profilePath)) { throw "Missing tenant profile: $profilePath" }
if (-not (Test-Path $corePath))    { throw "Missing core library: $corePath" }

if (-not (Test-Path (Join-Path $root "apply_variant_library.py"))) { throw "Missing apply_variant_library.py at repo root" }
if (-not (Test-Path (Join-Path $root "patch_must_variants.py")))   { throw "Missing patch_must_variants.py at repo root" }
if (-not (Test-Path (Join-Path $root "patch_parking_variants.py"))) { throw "Missing patch_parking_variants.py at repo root" }

if (-not (Test-Path $faqsSource)) { throw "Missing tenant faqs.json: $faqsSource" }

# Check for expand_variants.py if expansion is enabled
if ($ExpandVariants) {
  $expandScript = Join-Path (Join-Path $root "tools") "expand_variants.py"
  if (-not (Test-Path $expandScript)) { throw "Missing expand_variants.py at $expandScript" }
}

# Ensure backups dir exists
if (-not (Test-Path $backupsDir)) { New-Item -ItemType Directory -Path $backupsDir | Out-Null }

# Optional: Expand variants if requested
if ($ExpandVariants) {
  Write-Host "Expanding variants (automated expansion)..." -ForegroundColor Cyan
  $expandedPath = Join-Path $tenantDir "faqs_expanded.json"
  $expandScript = Join-Path (Join-Path $root "tools") "expand_variants.py"
  
  & python "$expandScript" --input "$faqsSource" --output "$expandedPath" --overwrite
  if ($LASTEXITCODE -ne 0) { throw "expand_variants.py failed" }
  
  # Use expanded file as source for pipeline
  $faqsSource = $expandedPath
  Write-Host "Using expanded FAQs as source: $expandedPath" -ForegroundColor Green
}

# Always rebuild faqs_variants.json from canonical source (faqs.json or faqs_expanded.json)
Copy-Item $faqsSource $faqFile -Force
Write-Host "Rebuilt faqs_variants.json from source" -ForegroundColor Yellow

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

  # 4) Warm up Render if using Render URL
  Warm-Up-Render -BaseUrl $AdminBase
  
  # 5) Upload
  Write-Host "Uploading FAQs (ADMIN)..." -ForegroundColor Cyan
  $token = Get-AdminToken
  Upload-Faqs -Path $faqFile -Token $token | Out-Null

  # 6) Run widget suite explicitly and trust its exit code
  Write-Host "Running suite (PUBLIC widget)..." -ForegroundColor Cyan
  $suite = Join-Path $root "run_suite_widget.ps1"
  if (-not (Test-Path $suite)) { throw "Missing run_suite_widget.ps1 at repo root: $suite" }

  $suiteOutput = & powershell -ExecutionPolicy Bypass -NoProfile -File $suite `
    -TenantId $TenantId `
    -Base $PublicBase `
    -Origin $Origin 2>&1 | Out-String

  $code = $LASTEXITCODE
  if ($code -ne 0) {
    Write-Host "`n=== Suite Failure Details ===" -ForegroundColor Red
    
    # Extract first failure from report
    $reportDir = Join-Path $root "reports"
    if (Test-Path $reportDir) {
      $latestReport = Get-ChildItem $reportDir -Filter "suite_${TenantId}_*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
      if ($latestReport) {
        $reportData = Get-Content $latestReport.FullName -Raw | ConvertFrom-Json
        # Find first result with non-empty fails array
        $firstFailure = $reportData.results | Where-Object { $_.fails -and $_.fails.Count -gt 0 } | Select-Object -First 1
        if ($firstFailure) {
          Write-Host "First failing test case:" -ForegroundColor Red
          Write-Host "  Name: $($firstFailure.name)" -ForegroundColor Yellow
          Write-Host "  Input: $($firstFailure.question)" -ForegroundColor Yellow
          Write-Host "  Expected: (check fails array)" -ForegroundColor Gray
          Write-Host "  Actual: faq_hit=$($firstFailure.x_faq_hit), branch=$($firstFailure.x_debug_branch), score=$($firstFailure.x_retrieval_score)" -ForegroundColor Gray
          Write-Host "  URL: $($PublicBase)/api/v2/widget/chat" -ForegroundColor Gray
          Write-Host "  Status: $($firstFailure.http)" -ForegroundColor Gray
          if ($firstFailure.fails) {
            Write-Host "  Failures: $($firstFailure.fails -join ', ')" -ForegroundColor Red
          }
          if ($firstFailure.replyText) {
            $respPreview = $firstFailure.replyText.Substring(0, [Math]::Min(200, $firstFailure.replyText.Length))
            Write-Host "  Response: $respPreview" -ForegroundColor Gray
          }
        } else {
          Write-Host "No failures found in report (but suite exited with code $code)" -ForegroundColor Yellow
        }
      }
    }
    throw "Suite failed with exit code $code"
  }

  # Promote last_good
  Copy-Item $faqFile $lastGood -Force
  Write-Host "✅ Suite PASS. Promoted to last_good." -ForegroundColor Green
}
catch {
  Write-Host "❌ Pipeline failed: $($_.Exception.Message)" -ForegroundColor Red

  if (Test-Path $lastGood) {
    Write-Host "Rolling back by re-uploading last_good (ADMIN)..." -ForegroundColor Yellow
    try {
      $token = Get-AdminToken
      Upload-Faqs -Path $lastGood -Token $token
      Copy-Item $lastGood $faqFile -Force
      Write-Host "Rollback upload OK." -ForegroundColor Green
    } catch {
      Write-Host "ROLLBACK FAILED" -ForegroundColor Red
      Write-Host "Last error: $($_.Exception.Message)" -ForegroundColor Red
      Write-Host "Failing URL: $($AdminBase.TrimEnd('/') + '/api/v2/admin/tenant/' + $TenantId + '/faqs')" -ForegroundColor Red
      # Stop here - don't continue if rollback fails
      exit 1
    }
  } else {
    Write-Host "No last_good found to rollback." -ForegroundColor Yellow
  }

  throw
}
