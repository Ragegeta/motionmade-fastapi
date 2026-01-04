cd C:\MM\motionmade-fastapi

$apiUrl = "https://api.motionmadebne.com.au"
$testTenant = "biz9_real"

Write-Host "`n=== ROBUSTNESS TEST: 30 DIVERSE QUERIES ===" -ForegroundColor Cyan

$testQueries = @(
    # Clean exact-ish matches
    @{q="how much do you charge"; expect="hit"; category="pricing"},
    @{q="what services do you offer"; expect="hit"; category="services"},
    @{q="do you clean ovens"; expect="hit"; category="services"},
    @{q="what's your cancellation policy"; expect="hit"; category="booking"},
    @{q="are you insured"; expect="hit"; category="trust"},
    
    # Messy/slang versions
    @{q="how much u charge"; expect="hit"; category="pricing-slang"},
    @{q="ur prices pls"; expect="hit"; category="pricing-slang"},
    @{q="do u do carpets"; expect="hit"; category="services-slang"},
    @{q="wat areas do u cover"; expect="hit"; category="logistics-slang"},
    @{q="can u come 2day"; expect="hit"; category="booking-slang"},
    
    # Fluff-wrapped
    @{q="hey quick one - what are your prices?"; expect="hit"; category="pricing-fluff"},
    @{q="hi there, just wondering about your service area"; expect="hit"; category="logistics-fluff"},
    @{q="sorry to bother you but do you have availability this week"; expect="hit"; category="booking-fluff"},
    
    # Multi-intent (should hit primary)
    @{q="prices and availability"; expect="hit"; category="multi"},
    @{q="do you do ovens? also what about fridges?"; expect="hit"; category="multi"},
    
    # Similar/ambiguous (tests DELTA threshold)
    @{q="cleaning"; expect="hit"; category="ambiguous"},
    @{q="price"; expect="hit"; category="ambiguous"},
    @{q="book"; expect="hit"; category="ambiguous"},
    
    # Should miss (unknown capabilities)
    @{q="do you do plumbing"; expect="miss"; category="unknown"},
    @{q="can you fix my roof"; expect="miss"; category="unknown"},
    @{q="do you paint houses"; expect="miss"; category="unknown"},
    
    # General knowledge (should not hit FAQ)
    @{q="why is the sky blue"; expect="general"; category="general"},
    @{q="what is the capital of france"; expect="general"; category="general"},
    
    # Junk (should clarify)
    @{q="???"; expect="clarify"; category="junk"},
    @{q="asdf"; expect="clarify"; category="junk"},
    @{q="hi"; expect="clarify"; category="junk"},
    
    # Edge cases
    @{q="WHAT ARE YOUR PRICES"; expect="hit"; category="caps"},
    @{q="prices?!?!"; expect="hit"; category="punctuation"},
    @{q="how much does the basic service cost exactly"; expect="hit"; category="verbose"}
)

$results = @()

foreach ($test in $testQueries) {
    $body = @{tenantId=$testTenant; customerMessage=$test.q} | ConvertTo-Json -Compress
    $tmpFile = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tmpFile, $body, [System.Text.Encoding]::UTF8)
    
    $response = curl.exe -s -i -X POST "$apiUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" --data-binary "@$tmpFile" 2>&1 | Out-String
    Remove-Item $tmpFile -Force
    
    # Parse headers
    $debugBranch = if ($response -match "x-debug-branch:\s*(\S+)") { $Matches[1] } else { "unknown" }
    $faqHit = $response -match "x-faq-hit:\s*true"
    $score = if ($response -match "x-retrieval-score:\s*([\d.]+)") { [math]::Round([double]$Matches[1], 3) } else { 0 }
    $isClarify = $response -match "rephrase"
    
    # Determine actual result
    $actual = if ($isClarify) { "clarify" }
              elseif ($debugBranch -match "general") { "general" }
              elseif ($faqHit) { "hit" }
              else { "miss" }
    
    $passed = $actual -eq $test.expect
    $icon = if ($passed) { "✅" } else { "❌" }
    
    $results += [PSCustomObject]@{
        Query = $test.q
        Category = $test.category
        Expected = $test.expect
        Actual = $actual
        Score = $score
        Branch = $debugBranch
        Passed = $passed
    }
    
    $scoreStr = if ($score -gt 0) { " (score: $score)" } else { "" }
    Write-Host "  $icon [$($test.category)] '$($test.q)' → $actual$scoreStr" -ForegroundColor $(if ($passed) { "Green" } else { "Red" })
}

# Summary
$passed = ($results | Where-Object { $_.Passed }).Count
$total = $results.Count

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "   ROBUSTNESS TEST RESULTS" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Passed: $passed / $total ($([math]::Round(($passed/$total)*100))%)" -ForegroundColor $(if ($passed -eq $total) { "Green" } else { "Yellow" })

# Breakdown by category
Write-Host "`nBy category:" -ForegroundColor Yellow
$results | Group-Object Category | ForEach-Object {
    $catPassed = ($_.Group | Where-Object { $_.Passed }).Count
    $catTotal = $_.Group.Count
    $pct = [math]::Round(($catPassed / $catTotal) * 100)
    $color = if ($pct -eq 100) { "Green" } elseif ($pct -ge 80) { "Yellow" } else { "Red" }
    Write-Host "  $($_.Name): $catPassed/$catTotal ($pct%)" -ForegroundColor $color
}

# Show failures
$failures = $results | Where-Object { -not $_.Passed }
if ($failures.Count -gt 0) {
    Write-Host "`nFailures:" -ForegroundColor Red
    $failures | ForEach-Object {
        Write-Host "  - '$($_.Query)' expected $($_.Expected), got $($_.Actual) (branch: $($_.Branch), score: $($_.Score))"
    }
}

# Score distribution
Write-Host "`nScore distribution for hits:" -ForegroundColor Yellow
$hitScores = $results | Where-Object { $_.Actual -eq "hit" } | Select-Object -ExpandProperty Score
if ($hitScores.Count -gt 0) {
    $avgScore = [math]::Round(($hitScores | Measure-Object -Average).Average, 3)
    $minScore = [math]::Round(($hitScores | Measure-Object -Minimum).Minimum, 3)
    $maxScore = [math]::Round(($hitScores | Measure-Object -Maximum).Maximum, 3)
    Write-Host "  Average: $avgScore | Min: $minScore | Max: $maxScore"
    
    # Score ranges
    $high = ($hitScores | Where-Object { $_ -ge 0.7 }).Count
    $med = ($hitScores | Where-Object { $_ -ge 0.5 -and $_ -lt 0.7 }).Count
    $low = ($hitScores | Where-Object { $_ -lt 0.5 }).Count
    Write-Host "  High (≥0.7): $high | Medium (0.5-0.7): $med | Low (<0.5): $low"
}

