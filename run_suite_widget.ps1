[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [string]$Base = "https://mm-client1-creator-backend-v1-0-0.abbedakbery14.workers.dev",
  [string]$Origin = "",
  [string]$Endpoint = "/api/v2/widget/chat",
  [ValidateSet("strict","stress")][string]$Mode = "strict",
  [int]$MaxTimeSec = 180,
  [switch]$ShowAnswers,
  [int]$TrimAnswerChars = 300,
  [string]$TestsPath = ""
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

if (-not $TestsPath) {
  $TestsPath = Join-Path $PSScriptRoot ("tests\{0}.json" -f $TenantId)
}
if (-not (Test-Path $TestsPath)) { throw "Missing tests file: $TestsPath" }

$testsArr = Get-Content $TestsPath -Raw | ConvertFrom-Json
if (-not $testsArr) { throw "Tests file loaded empty: $TestsPath" }

$tmpRoot = Join-Path $env:TEMP ("mm_suite_" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmpRoot | Out-Null

$reportDir = Join-Path $PSScriptRoot "reports"
if (-not (Test-Path $reportDir)) { New-Item -ItemType Directory -Path $reportDir | Out-Null }
$reportPath = Join-Path $reportDir ("suite_{0}_{1}_{2}.json" -f $TenantId, $Mode, (Get-Date -Format "yyyyMMdd_HHmmss"))

$score = @{
  strict_required = @{ hit=0; total=0 }
  stress_business = @{ hit=0; total=0 }
  stress_garbage  = @{ hit=0; total=0 }
  timeouts        = @{ hit=0; total=0 }
}

$hardFailCount = 0
$results = @()

try {
  foreach ($t in $testsArr) {
    Write-Host ("="*50)
    Write-Host $t.name
    Write-Host ""
    $q = [string]$t.question
    Write-Host "Q: $q"

    $id = [Guid]::NewGuid().ToString("N")
    $reqPath  = Join-Path $tmpRoot ("req_{0}.json" -f $id)
    $hdrPath  = Join-Path $tmpRoot ("hdr_{0}.txt" -f $id)
    $bodyPath = Join-Path $tmpRoot ("body_{0}.txt" -f $id)

    $url = ($Base.TrimEnd("/") + $Endpoint)

    $payloadObj = $null
    if ($Endpoint -match "widget/chat") {
      $payloadObj = @{ message = $q }
    } else {
      $payloadObj = @{ tenantId = $TenantId; customerMessage = $q }
    }
    $reqJson = $payloadObj | ConvertTo-Json -Compress
    Write-Utf8NoBomFile $reqPath $reqJson

    $curlArgs = @(
      "-sS",
      "--http1.1",
      "--connect-timeout","10",
      "--max-time",$MaxTimeSec.ToString(),
      "-D",$hdrPath,
      "-o",$bodyPath,
      "-X","POST",$url,
      "-H","Content-Type: application/json",
      "-H","Expect:",
      "--data-binary",("@"+$reqPath)
    )
    if ($Origin) { $curlArgs = $curlArgs + @("-H",("Origin: "+$Origin)) }

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $curlOk = $true
    try { & curl.exe @curlArgs | Out-Null } catch { $curlOk = $false }
    $sw.Stop()
    $timeMs = [int]$sw.ElapsedMilliseconds

    $hdrLines = @()
    if (Test-Path $hdrPath) { $hdrLines = Get-Content $hdrPath }

    $http = ""
    foreach ($l in $hdrLines) { if ($l -match '^HTTP\/') { $http = $l.Split(' ')[1]; break } }

    $branch   = Get-HeaderValue $hdrLines "x-debug-branch"
    $faqHit   = Get-HeaderValue $hdrLines "x-faq-hit"
    $tenantH  = Get-HeaderValue $hdrLines "x-tenantid"
    $gateHit  = Get-HeaderValue $hdrLines "x-fact-gate-hit"
    $topId    = Get-HeaderValue $hdrLines "x-top-faq-id"
    $scoreHdr = Get-HeaderValue $hdrLines "x-retrieval-score"

    Write-Host ("  http={0} time_ms={1}" -f $http, $timeMs)
    Write-Host ("  x-debug-branch={0}" -f $branch)
    if ($tenantH) { Write-Host ("  x-tenantid={0}" -f $tenantH) }
    if ($faqHit)  { Write-Host ("  x-faq-hit={0}" -f $faqHit) }
    if ($gateHit) { Write-Host ("  x-fact-gate-hit={0}" -f $gateHit) }
    if ($topId)   { Write-Host ("  x-top-faq-id={0}" -f $topId) }
    if ($scoreHdr){ Write-Host ("  x-retrieval-score={0}" -f $scoreHdr) }

    $bodyText = ""
    if (Test-Path $bodyPath) { $bodyText = Get-Content $bodyPath -Raw }

    $replyText = ""
    try { $replyText = (ConvertFrom-Json $bodyText).replyText } catch { $replyText = "" }

    $fails = @()

    if (-not $curlOk -or -not $http) {
      $fails += "FAIL: HTTP"
      $score.timeouts.total++
      $score.timeouts.hit++
    } else {
      $score.timeouts.total++
    }

    $expectBranches = @()
    if ($t.expect_debug_branch_any) { $expectBranches = @($t.expect_debug_branch_any) }
    if ($expectBranches.Count -gt 0) {
      $ok = $false
      foreach ($b in $expectBranches) { if ($branch -eq $b) { $ok = $true; break } }
      if (-not $ok) { $fails += ("FAIL: expected x-debug-branch in [{0}], got '{1}'" -f ($expectBranches -join ", "), $branch) }
    }

    if ($t.expect_faq_hit) {
      $want = ([string]$t.expect_faq_hit).ToLowerInvariant()
      $got  = ([string]$faqHit).ToLowerInvariant()
      if ($got -ne $want) {
        $fails += ("FAIL: expected x-faq-hit={0}, got '{1}' (top_faq_id={2} score={3} gate={4})" -f $want, $faqHit, $topId, $scoreHdr, $gateHit)
      }
    }

    if ($t.must_contain) {
      foreach ($tok in $t.must_contain) {
        if (-not ($replyText -like ("*"+$tok+"*"))) {
          $fails += ("FAIL: missing token '{0}' in replyText" -f $tok)
        }
      }
    }

    if ($ShowAnswers -or $fails.Count -gt 0) {
      $preview = $replyText
      if ($TrimAnswerChars -gt 0 -and $preview.Length -gt $TrimAnswerChars) {
        $preview = $preview.Substring(0,$TrimAnswerChars) + "..."
      }
      Write-Host ("  replyText: {0}" -f $preview)
    }

    if ($Mode -eq "strict") {
      $score.strict_required.total++
      if ($fails.Count -eq 0) { $score.strict_required.hit++ }
    }

    $severity = "hard"
    if ($t.severity) { $severity = [string]$t.severity }

    if ($fails.Count -gt 0) {
      foreach ($f in $fails) { Write-Host $f }
      if ($Mode -eq "strict" -or $severity -eq "hard") { $hardFailCount++ }
    }

    $results += [pscustomobject]@{
      name=$t.name
      question=$q
      http=$http
      time_ms=$timeMs
      x_debug_branch=$branch
      x_faq_hit=$faqHit
      x_fact_gate_hit=$gateHit
      x_tenantid=$tenantH
      x_top_faq_id=$topId
      x_retrieval_score=$scoreHdr
      replyText=$replyText
      fails=@($fails)
      severity=$severity
      category=($t.category)
    }
  }
}
finally {
  # best-effort cleanup (doesn't matter if it fails)
  try { Remove-Item $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue } catch {}
}

$report = [pscustomobject]@{
  tenantId=$TenantId
  mode=$Mode
  base=$Base
  origin=$Origin
  endpoint=$Endpoint
  generated_at=(Get-Date).ToString("s")
  hardFailCount=$hardFailCount
  score=$score
  results=@($results)
}
$enc = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($reportPath, ($report | ConvertTo-Json -Depth 12), $enc)

Write-Host ""
Write-Host "SCORE SUMMARY:"
foreach ($k in $score.Keys) {
  $t = $score[$k].total
  if ($t -gt 0) {
    $h = $score[$k].hit
    Write-Host ("  {0}: {1}/{2}" -f $k, $h, $t)
  }
}
Write-Host ""
if ($hardFailCount -eq 0) {
  Write-Host ("✅ CHECK PASS. Report: {0}" -f $reportPath)
  exit 0
} else {
  Write-Host ("❌ CHECK FAIL ({0} hard tests failed). Report: {1}" -f $hardFailCount, $reportPath)
  exit 1
}