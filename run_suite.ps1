param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [string]$Base = "",
  [string]$TestFile = ""
)

$tenantTest = if ($TestFile) { $TestFile } else { ".\tests\$TenantId.json" }
if (-not (Test-Path $tenantTest)) { throw "Missing test file: $tenantTest" }

$cfg = Get-Content $tenantTest -Raw | ConvertFrom-Json
$base = if ($Base) { $Base } else { $cfg.base }
$endpoint = $cfg.endpoint

function Call-Api([string]$q) {
  $uri = ($base.TrimEnd("/") + $endpoint)
  $body = @{ tenantId = $TenantId; customerMessage = $q } | ConvertTo-Json -Compress
  return Invoke-WebRequest -UseBasicParsing -Method Post -Uri $uri -ContentType "application/json" -Body $body -TimeoutSec 180
}

$fail = 0
foreach ($t in $cfg.tests) {
  $name = $t.name
  $q    = $t.question
  $allowed = @($t.expect_debug_branch_any)
  $must = @($t.must_contain)

  Write-Host "=================================================="
  Write-Host $name
  Write-Host ""
  Write-Host "Q: $q"

  try {
    $resp = Call-Api $q
    $dbg  = $resp.Headers["x-debug-branch"]

    $replyText = $null
    try { $replyText = ($resp.Content | ConvertFrom-Json).replyText }
    catch { $replyText = $resp.Content }

    Write-Host "  x-debug-branch=$dbg"
    if ($replyText) { Write-Host "  replyText=$replyText" }

    $okBranch = $true
    if ($allowed -and $allowed.Count -gt 0) { $okBranch = $allowed -contains $dbg }

    $okMust = $true
    if ($must -and $must.Count -gt 0) {
      foreach ($m in $must) {
        if (-not $replyText) { $okMust = $false; break }
        if ($replyText -notlike "*$m*") {
          Write-Host "FAIL: missing token '$m' in replyText" -ForegroundColor Red
          $okMust = $false
        }
      }
    }

    if ($okBranch -and $okMust) { Write-Host "PASS" }
    else {
      if (-not $okBranch) { Write-Host "FAIL: expected x-debug-branch in $($allowed -join ', '), got $dbg" -ForegroundColor Red }
      $fail++
    }
  }
  catch {
    $msg = $_.Exception.Message
    $bodyText = ""
    try {
      $stream = $_.Exception.Response.GetResponseStream()
      if ($stream) {
        $reader = New-Object System.IO.StreamReader($stream)
        $bodyText = $reader.ReadToEnd()
      }
    } catch {}

    if ($bodyText) { Write-Host "FAIL: $msg`n  error_body=$bodyText" -ForegroundColor Red }
    else { Write-Host "FAIL: $msg" -ForegroundColor Red }
    $fail++
  }
}

Write-Host "=================================================="
if ($fail -eq 0) { Write-Host "✅ Suite PASS" -ForegroundColor Green; exit 0 }
else { Write-Host "❌ Suite FAIL ($fail failing)" -ForegroundColor Red; exit 1 }
