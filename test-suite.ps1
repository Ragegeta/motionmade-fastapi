Set-Location -Path (Split-Path -Parent $MyInvocation.MyCommand.Path)

$baseUrl = "https://api.motionmadebne.com.au/api/v2/generate-quote-reply"
$fallbackNeedle = "For accurate details, please contact us directly"

function Invoke-TestRequest {
  param(
    [Parameter(Mandatory=$true)][string]$Question,
    [int]$Retries = 3
  )

  $payload = @{
    tenantId="motionmade"
    cleanType="standard"
    bedrooms=2
    bathrooms=1
    condition="average"
    pets="no"
    addons=@()
    preferredTiming="Friday morning"
    customerMessage=$Question
  } | ConvertTo-Json -Depth 6

  for ($i=0; $i -le $Retries; $i++) {
    try {
      return Invoke-WebRequest -UseBasicParsing -Uri $baseUrl -Method POST -ContentType "application/json" -Body $payload -TimeoutSec 60
    } catch {
      if ($i -eq $Retries) { return $null }
      Start-Sleep -Seconds 1
    }
  }
}

function Get-ReplyText($resp) {
  try { return (($resp.Content | ConvertFrom-Json).replyText) } catch { return "" }
}

function Print-Result {
  param([string]$Question, $Resp)

  if (-not $Resp) {
    Write-Host ""
    Write-Host "Q: $Question" -ForegroundColor Yellow
    Write-Host "  HTTP FAIL" -ForegroundColor Red
    return
  }

  $h = $Resp.Headers
  $reply = Get-ReplyText $Resp

  Write-Host ""
  Write-Host "Q: $Question" -ForegroundColor Yellow
  Write-Host ("  x-build={0}  x-debug-branch={1}  x-fact-gate-hit={2}  x-fact-domain={3}  x-faq-hit={4}  x-score={5}  x-delta={6}  x-top-faq-id={7}" -f `
    $h['x-build'], $h['x-debug-branch'], $h['x-fact-gate-hit'], $h['x-fact-domain'], $h['x-faq-hit'], $h['x-retrieval-score'], $h['x-retrieval-delta'], $h['x-top-faq-id'])
  Write-Host ("  x-proxy-upstream={0}  x-proxy-status={1}  x-proxy-path={2}" -f `
    $h['x-proxy-upstream'], $h['x-proxy-status'], $h['x-proxy-path'])
  Write-Host "  replyText=$reply"
}

function Assert-Contains {
  param([string]$Text, [string]$Needle, [string]$FailMsg)
  if ($Text -notlike "*$Needle*") { throw $FailMsg }
}

function Run-Test {
  param(
    [string]$Name,
    [string]$Question,
    [ValidateSet("FACT_ACCEPT","BUSINESS_FALLBACK","GENERAL_OK")][string]$Expect,
    [string]$MustContain = ""
  )

  Write-Host "==================================================" -ForegroundColor Cyan
  Write-Host "$Name" -ForegroundColor Cyan

  $resp = Invoke-TestRequest -Question $Question
  Print-Result -Question $Question -Resp $resp
  if (-not $resp) {
    Write-Host "FAIL: HTTP FAIL" -ForegroundColor Red
    return
  }

  try {
    $h = $resp.Headers
    $branch = $h['x-debug-branch']
    $gate   = $h['x-fact-gate-hit']
    $faqHit = $h['x-faq-hit']
    $reply  = Get-ReplyText $resp

    if ($Expect -eq "FACT_ACCEPT") {
      if (($branch -ne "fact_hit") -and ($branch -ne "fact_rewrite_hit")) { throw "expected fact_hit or fact_rewrite_hit, got $branch" }
      if ($faqHit -ne "true") { throw "expected x-faq-hit=true" }
      if ($MustContain) { Assert-Contains $reply $MustContain "expected replyText to contain '$MustContain'" }
    }

    if ($Expect -eq "BUSINESS_FALLBACK") {
      if ($gate -ne "true") { throw "expected x-fact-gate-hit=true (business) but got $gate" }
      if ($branch -eq "general_ok") { throw "unsafe routing: business question went general_ok" }
      Assert-Contains $reply $fallbackNeedle "expected fallback replyText"
    }

    if ($Expect -eq "GENERAL_OK") {
      if ($branch -ne "general_ok") { throw "expected general_ok, got $branch" }
      if ($gate -ne "false") { throw "expected x-fact-gate-hit=false for general" }
    }

    Write-Host "PASS" -ForegroundColor Green
  }
  catch {
    Write-Host ("FAIL: {0}" -f $_.Exception.Message) -ForegroundColor Red
  }
}

# -------- Second-opinion TEST SET --------
Run-Test -Name "A) Oven add-on pricing (must hit)" `
  -Question "How much extra is the oven add-on?" `
  -Expect "FACT_ACCEPT" `
  -MustContain "$89"

Run-Test -Name "B) Service area (must hit)" `
  -Question "Do you cover Brisbane inner north?" `
  -Expect "FACT_ACCEPT"

Run-Test -Name "C) Supplies/equipment (must hit)" `
  -Question "Do I need to supply anything or do you bring gear?" `
  -Expect "FACT_ACCEPT"

Run-Test -Name "D) Unknown capability (must fallback; never general_ok)" `
  -Question "Can you steam clean a couch?" `
  -Expect "BUSINESS_FALLBACK"

Run-Test -Name "E) Unknown capability (must fallback; never general_ok)" `
  -Question "Do you do pressure washing?" `
  -Expect "BUSINESS_FALLBACK"

Run-Test -Name "F) General knowledge (must be general_ok)" `
  -Question "Why is the sky blue?" `
  -Expect "GENERAL_OK"
