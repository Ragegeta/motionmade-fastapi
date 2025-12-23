Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$base     = "https://motionmade-fastapi.onrender.com"
$tenantId = "motionmade"
$root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$faqFile  = Join-Path $root "faqs_variants.json"
$libFile  = Join-Path $root "variant_library.json"
$suite    = Join-Path $root "test-suite.ps1"

function Get-AdminToken {
  $envPath = Join-Path $root ".env"
  $line = Get-Content $envPath | Where-Object { $_ -match '^\s*ADMIN_TOKEN\s*=' } | Select-Object -First 1
  if (-not $line) { throw "ADMIN_TOKEN not found in .env" }
  return ($line -replace '^\s*ADMIN_TOKEN\s*=\s*', '').Trim().Trim('"').Trim("'")
}

function Upload-FaqsCurl([string]$File, [string]$Token) {
  if (-not (Test-Path $File)) { throw "FAQ file not found: $File" }
  $url = "$base/admin/tenant/$tenantId/faqs"

  $args = @(
    "--http1.1", "-sS", "-i",
    "--retry", "3", "--retry-delay", "2", "--retry-all-errors",
    "--max-time", "180",
    "-X", "PUT", $url,
    "-H", "Authorization: Bearer $Token",
    "-H", "Content-Type: application/json",
    "--data-binary", "@$File"
  )

  $out = & curl.exe @args 2>&1
  if ($LASTEXITCODE -ne 0) { throw "Upload failed (curl exit $LASTEXITCODE):`n$out" }
  if ($out -notmatch "HTTP/\S+\s+200") { throw "Upload failed (no HTTP 200):`n$out" }

  Write-Host "Upload OK (HTTP 200)" -ForegroundColor Green
}

function Run-SuiteText {
  return (& powershell -ExecutionPolicy Bypass -NoProfile -File $suite 2>&1 | Out-String)
}

# ---------- main ----------
if (-not (Test-Path $faqFile)) { throw "Missing faqs_variants.json at $faqFile" }
if (-not (Test-Path $libFile)) { throw "Missing variant_library.json at $libFile" }

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$rollbackBak = Join-Path $root ("faqs_variants.json.rollback_" + $ts)
Copy-Item $faqFile $rollbackBak -Force

Write-Host "Applying targeted variant library (prevents FAQ collisions)..." -ForegroundColor Cyan
python (Join-Path $root "apply_variant_library.py") --infile $faqFile --outfile $faqFile --library $libFile
if ($LASTEXITCODE -ne 0) { throw "apply_variant_library.py failed" }

$token = Get-AdminToken

Write-Host "Uploading FAQs..." -ForegroundColor Cyan
Upload-FaqsCurl -File $faqFile -Token $token

Write-Host "Running suite..." -ForegroundColor Cyan
$out = Run-SuiteText
Write-Host $out

if ($out -match "FAIL:") {
  Write-Host "Suite FAIL -> rolling back to previous local file and re-uploading..." -ForegroundColor Red
  Copy-Item $rollbackBak $faqFile -Force
  Upload-FaqsCurl -File $faqFile -Token $token
  $out2 = Run-SuiteText
  Write-Host $out2
  if ($out2 -match "FAIL:") {
    throw "Rollback still failing. Stop and inspect faqs_variants.json variants for collisions."
  } else {
    Write-Host "Rollback restored a PASS state." -ForegroundColor Green
  }
} else {
  Write-Host "Suite PASS. Done." -ForegroundColor Green
}