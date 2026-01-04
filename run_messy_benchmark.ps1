[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [Parameter(Mandatory=$false)][string]$ApiUrl = "https://api.motionmadebne.com.au",
  [Parameter(Mandatory=$false)][switch]$ShowAll,
  [Parameter(Mandatory=$false)][switch]$JsonOutput
)

$ErrorActionPreference = "Stop"
$scriptDir = $PSScriptRoot

# Load benchmark suite
$benchmarkPath = Join-Path $scriptDir "tests" "messy_benchmark.json"
if (-not (Test-Path $benchmarkPath)) {
    Write-Error "Benchmark file not found: $benchmarkPath"
    exit 1
}

$benchmark = Get-Content $benchmarkPath -Raw | ConvertFrom-Json
$tests = $benchmark.tests
$thresholds = $benchmark.pass_thresholds

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MESSY BENCHMARK: $TenantId" -ForegroundColor Cyan
Write-Host "  Tests: $($tests.Count) | Min hit rate: $($thresholds.min_hit_rate * 100)%" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$results = @()

foreach ($test in $tests) {
    # Build request
    $body = @{tenantId=$TenantId; customerMessage=$test.question} | ConvertTo-Json -Compress
    $tempFile = [System.IO.Path]::GetTempFileName()
    $body | Set-Content -Path $tempFile -Encoding UTF8
    
    try {
        $response = curl.exe -s -i -X POST "$ApiUrl/api/v2/generate-quote-reply" `
            -H "Content-Type: application/json" `
            --data-binary "@$tempFile" 2>&1
    } finally {
        Remove-Item $tempFile -ErrorAction SilentlyContinue
    }
    
    # Parse response
    $score = if ($response -match "(?i)x-retrieval-score:\s*([\d.]+)") { [math]::Round([double]$Matches[1], 3) } else { $null }
    $faqHit = $response -match "(?i)x-faq-hit:\s*true"
    $branch = if ($response -match "(?i)x-debug-branch:\s*(\S+)") { $Matches[1] } else { "unknown" }
    $isClarify = $response -match "rephrase"
    
    # Determine actual outcome
    $actualHit = $faqHit
    $actualBranch = if ($isClarify) { "clarify" } else { $branch }
    
    # Check pass/fail
    $passed = $true
    $reason = ""
    
    if ($test.expect_hit -eq $true -and -not $actualHit) {
        $passed = $false
        $reason = "Expected HIT, got MISS (score: $score)"
    } elseif ($test.expect_hit -eq $false -and $actualHit) {
        $passed = $false
        $reason = "Expected MISS, got HIT"
    }
    
    if ($test.expect_branch -and $actualBranch -ne $test.expect_branch) {
        $passed = $false
        $reason = "Expected branch '$($test.expect_branch)', got '$actualBranch'"
    }
    
    if ($test.expect_branch_any -and $test.expect_branch_any -notcontains $actualBranch) {
        $passed = $false
        $reason = "Expected branch in [$($test.expect_branch_any -join ', ')], got '$actualBranch'"
    }
    
    $result = [PSCustomObject]@{
        Id = $test.id
        Category = $test.category
        Question = $test.question
        ExpectHit = $test.expect_hit
        ActualHit = $actualHit
        Score = $score
        Branch = $actualBranch
        Passed = $passed
        Reason = $reason
    }
    
    $results += $result
    
    # Display
    $icon = if ($passed) { "✅" } else { "❌" }
    $hitStr = if ($actualHit) { "HIT" } else { "MISS" }
    $scoreStr = if ($score) { "($score)" } else { "(n/a)" }
    
    if (-not $passed -or $ShowAll) {
        Write-Host "  $icon [$($test.id)] $hitStr $scoreStr - $($test.question)" -ForegroundColor $(if ($passed) { "Green" } else { "Red" })
        if (-not $passed) {
            Write-Host "       → $reason" -ForegroundColor Yellow
        }
    }
}

# Calculate metrics
$totalTests = $results.Count
$passedTests = ($results | Where-Object { $_.Passed }).Count
$failedTests = $totalTests - $passedTests

$expectHitTests = $results | Where-Object { $_.ExpectHit -eq $true }
$actualHits = ($expectHitTests | Where-Object { $_.ActualHit }).Count
$hitRate = if ($expectHitTests.Count -gt 0) { [math]::Round($actualHits / $expectHitTests.Count, 3) } else { 1 }

$expectMissTests = $results | Where-Object { $_.ExpectHit -eq $false }
$wrongHits = ($expectMissTests | Where-Object { $_.ActualHit }).Count
$wrongHitRate = if ($expectMissTests.Count -gt 0) { [math]::Round($wrongHits / $expectMissTests.Count, 3) } else { 0 }

$fallbackTests = $results | Where-Object { $_.Branch -match "fallback" -and $_.ExpectHit -eq $true }
$fallbackRate = if ($expectHitTests.Count -gt 0) { [math]::Round($fallbackTests.Count / $expectHitTests.Count, 3) } else { 0 }

# Summary
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  RESULTS" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

Write-Host "  Tests: $passedTests / $totalTests passed" -ForegroundColor $(if ($passedTests -eq $totalTests) { "Green" } else { "Yellow" })
Write-Host "  Hit rate: $($hitRate * 100)% (threshold: $($thresholds.min_hit_rate * 100)%)" -ForegroundColor $(if ($hitRate -ge $thresholds.min_hit_rate) { "Green" } else { "Red" })
Write-Host "  Fallback rate: $($fallbackRate * 100)% (threshold: $($thresholds.max_fallback_rate * 100)%)" -ForegroundColor $(if ($fallbackRate -le $thresholds.max_fallback_rate) { "Green" } else { "Red" })
Write-Host "  Wrong hit rate: $($wrongHitRate * 100)% (threshold: $($thresholds.max_wrong_hit_rate * 100)%)" -ForegroundColor $(if ($wrongHitRate -le $thresholds.max_wrong_hit_rate) { "Green" } else { "Red" })

# Category breakdown
Write-Host "`n  By category:" -ForegroundColor Yellow
$results | Group-Object Category | ForEach-Object {
    $catPassed = ($_.Group | Where-Object { $_.Passed }).Count
    $catTotal = $_.Group.Count
    $pct = [math]::Round(($catPassed / $catTotal) * 100)
    $color = if ($catPassed -eq $catTotal) { "Green" } elseif ($pct -ge 70) { "Yellow" } else { "Red" }
    Write-Host "    $($_.Name): $catPassed/$catTotal ($pct%)" -ForegroundColor $color
}

# Gate check
$gatePass = ($hitRate -ge $thresholds.min_hit_rate) -and 
            ($fallbackRate -le $thresholds.max_fallback_rate) -and 
            ($wrongHitRate -le $thresholds.max_wrong_hit_rate)

Write-Host "`n========================================" -ForegroundColor $(if ($gatePass) { "Green" } else { "Red" })
if ($gatePass) {
    Write-Host "  ✅ BENCHMARK GATE: PASS" -ForegroundColor Green
} else {
    Write-Host "  ❌ BENCHMARK GATE: FAIL" -ForegroundColor Red
}
Write-Host "========================================" -ForegroundColor $(if ($gatePass) { "Green" } else { "Red" })

# Show worst misses
$misses = $results | Where-Object { -not $_.Passed -and $_.ExpectHit -eq $true } | Sort-Object Score -Descending
if ($misses.Count -gt 0) {
    Write-Host "`n  Worst misses (expected HIT but got MISS):" -ForegroundColor Yellow
    $misses | Select-Object -First 5 | ForEach-Object {
        Write-Host "    [$($_.Id)] score=$($_.Score) '$($_.Question)'" -ForegroundColor Red
    }
}

# JSON output option
if ($JsonOutput) {
    $output = @{
        tenant_id = $TenantId
        timestamp = (Get-Date -Format "o")
        total_tests = $totalTests
        passed_tests = $passedTests
        hit_rate = $hitRate
        fallback_rate = $fallbackRate
        wrong_hit_rate = $wrongHitRate
        gate_pass = $gatePass
        failures = ($results | Where-Object { -not $_.Passed } | Select-Object Id, Question, Score, Reason)
    }
    $output | ConvertTo-Json -Depth 5
}

