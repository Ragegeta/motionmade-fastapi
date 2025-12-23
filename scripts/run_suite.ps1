[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [string]$Base = "https://motionmade-fastapi.onrender.com",
  [string]$TestFile = ""
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $root

$tenantTest = if ($TestFile) { $TestFile } else { Join-Path (Join-Path $repo "tests") "$TenantId.json" }
if (-not (Test-Path $tenantTest)) { throw "Missing test file: $tenantTest" }

# JSON validity
try { $cfg = Get-Content $tenantTest -Raw | ConvertFrom-Json } catch { throw "Invalid JSON in test file: $tenantTest" }

$base = if ($Base) { $Base } else { $cfg.base }
$endpoint = $cfg.endpoint
if (-not $endpoint) { throw "tests JSON missing 'endpoint' field" }

function Call-Api([string]$q) {
  $uri = ($base.TrimEnd("/") + $endpoint)

  # IMPORTANT: server expects tenantId + customerMessage
  $body = @{
    tenantId        = $TenantId
    customerMessage = $q
  } | ConvertTo-Json -Compress

  return Invoke-WebRequest -UseBasicParsing -Method Post -Uri $uri -ContentType "application/json" -Body $body -TimeoutSec 180
}

function Get-H([Microsoft.PowerShell.Commands.WebResponseObject]$resp, [string]$k) {
  # headers are case-insensitive, but PS returns canonical keys sometimes
  $v = $resp.Headers[$k]
  if ($null -eq $v) { $v = $resp.Headers[$k.ToLower()] }
  if ($null -eq $v) { $v = $resp.Headers[$k.ToUpper()] }
  return $v
}

$fail = 0
$failing = @()

# strict: missing observability headers = fail
$requiredHeaders = @(
  "x-build",
  "x-debug-branch",
  "x-fact-gate-hit",
  "x-fact-domain",
  "x-faq-hit"
  # optional today (enable when server adds them):
  # "x-tenant-id",
  # "x-faq-set-version"
)

foreach ($t in $cfg.tests) {
  $name = $t.name
  $q    = $t.question

  Write-Host "=================================================="
  Write-Host $name
  Write-Host ""
  Write-Host "Q: $q"

  try {
    $resp = Call-Api $q

    $dbg   = (Get-H $resp "x-debug-branch")
    $factG = (Get-H $resp "x-fact-gate-hit")
    $factD = (Get-H $resp "x-fact-domain")
    $faqH  = (Get-H $resp "x-faq-hit")
    $build = (Get-H $resp "x-build")
    $score = (Get-H $resp "x-score")

    $replyText = ""
    try { $replyText = ($resp.Content | ConvertFrom-Json).replyText } catch { $replyText = $resp.Content }

    # Observability gate
    $missing = @()
    foreach ($h in $requiredHeaders) {
      if (-not (Get-H $resp $h)) { $missing += $h }
    }
    if ($missing.Count -gt 0) {
      Write-Host "FAIL: missing required headers: $($missing -join ', ')"
      $fail++
      $failing += $name
      continue
    }

    Write-Host "  x-build=$build"
    Write-Host "  x-debug-branch=$dbg  x-fact-gate-hit=$factG  x-fact-domain=$factD  x-faq-hit=$faqH  x-score=$score"
    if ($replyText) { Write-Host "  replyText=$replyText" }

    $ok = $true

    # critical safety gate: business/capability questions must NEVER return general_ok
    if ($t.is_business_question -eq $true -and $dbg -eq "general_ok") { $ok = $false }

    # expected branch
    if ($t.expect_debug_branch_any) {
      if (-not ($t.expect_debug_branch_any -contains $dbg)) { $ok = $false }
    }

    # fact gate expectation (true/false)
    if ($null -ne $t.expect_fact_gate_hit) {
      $want = [string]$t.expect_fact_gate_hit
      $got  = [string]$factG
      if ($want.ToLower() -ne $got.ToLower()) { $ok = $false }
    }

    # faq hit expectation (true/false)
    if ($null -ne $t.expect_faq_hit) {
      $want = [string]$t.expect_faq_hit
      $got  = [string]$faqH
      if ($want.ToLower() -ne $got.ToLower()) { $ok = $false }
    }

    # score threshold if present (only meaningful when retrieval ran)
    if ($t.min_score) {
      $min = [double]$t.min_score
      $s   = 0.0
      try { $s = [double]$score } catch { $s = 0.0 }
      if ($s -lt $min) { $ok = $false }
    }

    # fallback reply check (prefix match is safer than exact)
    if ($t.expect_reply_prefix) {
      if (-not ($replyText.StartsWith([string]$t.expect_reply_prefix))) { $ok = $false }
    }

    if ($ok) {
      Write-Host "PASS"
    } else {
      Write-Host "FAIL"
      $fail++
      $failing += $name
    }

  } catch {
    Write-Host "FAIL: request error: $($_.Exception.Message)"
    $fail++
    $failing += $name
  }
}

Write-Host "=================================================="
if ($fail -eq 0) {
  Write-Host "✅ Suite PASS" -ForegroundColor Green
  exit 0
} else {
  Write-Host "❌ Suite FAIL ($fail failing): $($failing -join '; ')" -ForegroundColor Red
  exit 1
}
