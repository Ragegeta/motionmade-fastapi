param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [string]$Base = "",
  [string]$TestFile = ""
)

$tenantTest = if ($TestFile) { $TestFile } else { ".\tests\$TenantId.json" }
if (-not (Test-Path $tenantTest)) {
  throw "Missing test file: $tenantTest"
}

$cfg = Get-Content $tenantTest -Raw | ConvertFrom-Json
$base = if ($Base) { $Base } else { $cfg.base }
$endpoint = $cfg.endpoint

function Call-Api([string]$q) {
  $uri = ($base.TrimEnd("/") + $endpoint)

  # ✅ Correct payload for your API
  $body = @{
    tenantId        = $TenantId
    customerMessage = $q
  } | ConvertTo-Json -Compress

  return Invoke-WebRequest -UseBasicParsing -Method Post -Uri $uri -ContentType "application/json" -Body $body -TimeoutSec 180
}

$fail = 0
foreach ($t in $cfg.tests) {
  $name = $t.name
  $q    = $t.question
  $allowed = @($t.expect_debug_branch_any)

  Write-Host "=================================================="
  Write-Host $name
  Write-Host ""
  Write-Host "Q: $q"

  try {
    $resp = Call-Api $q
    $dbg  = $resp.Headers["x-debug-branch"]

    $replyText = $null
    try {
      $replyText = ($resp.Content | ConvertFrom-Json).replyText
    } catch {
      $replyText = $resp.Content
    }

    Write-Host "  x-debug-branch=$dbg"
    if ($replyText) { Write-Host "  replyText=$replyText" }

    $ok = $true
    if ($allowed -and $allowed.Count -gt 0) {
      $ok = $allowed -contains $dbg
    }

    if ($ok) { Write-Host "PASS" }
    else {
      Write-Host "FAIL: expected x-debug-branch in $($allowed -join ', '), got $dbg"
      $fail++
    }
  }
  catch {
    $msg = $_.Exception.Message
    $bodyText = ""

    # Try to show HTTP body if present
    try {
      $stream = $_.Exception.Response.GetResponseStream()
      if ($stream) {
        $reader = New-Object System.IO.StreamReader($stream)
        $bodyText = $reader.ReadToEnd()
      }
    } catch {}

    if ($bodyText) {
      Write-Host "FAIL: $msg"
      Write-Host "  error_body=$bodyText"
    } else {
      Write-Host "FAIL: $msg"
    }
    $fail++
  }
}

Write-Host "=================================================="
if ($fail -eq 0) { Write-Host "✅ Suite PASS" -ForegroundColor Green; exit 0 }
else { Write-Host "❌ Suite FAIL ($fail failing)" -ForegroundColor Red; exit 1 }
