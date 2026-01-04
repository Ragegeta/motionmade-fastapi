[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [string]$Base = "https://api.motionmadebne.com.au",
  [string]$Origin = "",
  [string]$Endpoint = "/api/v2/generate-quote-reply"
)

$ErrorActionPreference = "Stop"

function Write-Utf8NoBomFile([string]$path, [string]$text) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($path, $text, $enc)
}

function Get-HeaderValue([string[]]$lines, [string]$name) {
  $prefix = ($name + ":").ToLowerInvariant()
  foreach ($l in $lines) {
    $ll = $l.ToLowerInvariant()
    if ($ll.StartsWith($prefix)) { return $l.Split(":",2)[1].Trim() }
  }
  return ""
}

$testFile = Join-Path $PSScriptRoot ("tests\{0}.json" -f $TenantId)
if (-not (Test-Path $testFile)) { throw "Missing test file: $testFile" }

$tests = Get-Content $testFile -Raw | ConvertFrom-Json

foreach ($t in $tests) {
  Write-Host ("="*50)
  Write-Host $t.name

  $q = [string]$t.question
  Write-Host ""
  Write-Host "Q: $q"

  $req = @{ tenantId = $TenantId; customerMessage = $q } | ConvertTo-Json -Compress

  $tmpDir = Join-Path $env:TEMP "mm_suite"
  if (-not (Test-Path $tmpDir)) { New-Item -ItemType Directory -Path $tmpDir | Out-Null }

  $reqPath = Join-Path $tmpDir "req.json"
  $hdrPath = Join-Path $tmpDir "hdr.txt"
  $bodyPath = Join-Path $tmpDir "body.txt"

  Write-Utf8NoBomFile $reqPath $req
  if (Test-Path $hdrPath) { Remove-Item $hdrPath -Force }
  if (Test-Path $bodyPath) { Remove-Item $bodyPath -Force }

  $url = ($Base.TrimEnd("/") + $Endpoint)

  $curlArgs = @(
    "-sS","-D",$hdrPath,"-o",$bodyPath,
    "-X","POST",$url,
    "-H","Content-Type: application/json",
    "--data-binary",("@"+$reqPath)
  )
  if ($Origin) { $curlArgs = $curlArgs[0..7] + @("-H",("Origin: "+$Origin)) + $curlArgs[8..($curlArgs.Length-1)] }

  & curl.exe @curlArgs | Out-Null

  $hdrLines = @()
  if (Test-Path $hdrPath) { $hdrLines = Get-Content $hdrPath }

  $http = ""
  foreach ($l in $hdrLines) { if ($l -match '^HTTP\/') { $http = $l.Split(' ')[1]; break } }

  $branch = Get-HeaderValue $hdrLines "x-debug-branch"

  Write-Host ("  http={0}" -f $http)
  Write-Host ("  x-debug-branch={0}" -f $branch)

  $bodyText = ""
  if (Test-Path $bodyPath) { $bodyText = Get-Content $bodyPath -Raw }

  $replyText = ""
  try { $replyText = (ConvertFrom-Json $bodyText).replyText } catch { $replyText = "" }

  if ($t.expect_debug_branch_any) {
    $ok = $false
    foreach ($b in $t.expect_debug_branch_any) { if ($branch -eq $b) { $ok = $true; break } }
    if (-not $ok) { Write-Host ("FAIL: expected x-debug-branch in {0}, got {1}" -f ($t.expect_debug_branch_any -join ", "), $branch) }
  }

  if ($t.must_contain) {
    foreach ($tok in $t.must_contain) {
      if (-not ($replyText -like ("*"+$tok+"*"))) {
        Write-Host ("FAIL: missing token '{0}' in replyText" -f $tok)
      }
    }
  }
}

# Summary
if ($LASTEXITCODE -ne 0) { exit 1 }
