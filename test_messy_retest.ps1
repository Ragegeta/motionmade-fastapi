$apiUrl = "https://api.motionmadebne.com.au"

# These were the failures from the earlier messy test
$tests = @(
    # These 5 MISSED before (should hit)
    @{q="hw much 4 sparky"; expect="hit"},
    @{q="saftey swich keeps goin off"; expect="hit"},
    @{q="switchbord making noise"; expect="hit"},
    @{q="r u licenced"; expect="hit"},
    @{q="pwr out half house"; expect="hit"},
    
    # These 2 WRONGLY HIT before (should miss)
    @{q="need plumbr asap"; expect="miss"},
    @{q="solar panls broken"; expect="miss"},
    
    # Add a few more messy should-hits
    @{q="smok alarm wont stop beepin"; expect="hit"},
    @{q="fan not workin anymore"; expect="hit"},
    @{q="lights flickring heaps"; expect="hit"},
    @{q="urgnt need elec"; expect="hit"},
    @{q="cn u come 2day"; expect="hit"},
    
    # Add more should-miss
    @{q="aircon busted"; expect="miss"},
    @{q="gas stov not workin"; expect="miss"},
    @{q="can u paint my hous"; expect="miss"}
)

$hitCount = 0; $shouldHit = 0
$wrongHits = 0; $shouldMiss = 0

Write-Host "=== RE-TEST MESSY QUERIES ===" -ForegroundColor Cyan

foreach ($t in $tests) {
    $body = "{`"tenantId`":`"sparkys_electrical`",`"customerMessage`":`"$($t.q)`"}"
    
    # Save body to file to avoid escaping issues
    $body | Out-File -FilePath "test_body_$($t.q -replace '[^\w]', '_').json" -Encoding utf8 -NoNewline
    
    $response = curl.exe -s -i -X POST "$apiUrl/api/v2/generate-quote-reply" `
        -H "Content-Type: application/json" `
        --data-binary "@test_body_$($t.q -replace '[^\w]', '_').json" 2>&1 | Out-String
    
    # Parse response
    $hit = $response -match "x-faq-hit:\s*true"
    if ($response -match "x-retrieval-stage:\s*([^\r\n]+)") {
        $stage = $Matches[1].Trim()
    } else {
        $stage = "?"
    }
    
    $actual = if ($hit) { "HIT" } else { "MISS" }
    $passed = ($hit -and $t.expect -eq "hit") -or (-not $hit -and $t.expect -eq "miss")
    
    if ($t.expect -eq "hit") { 
        $shouldHit++
        if ($hit) { $hitCount++ } 
    }
    if ($t.expect -eq "miss") { 
        $shouldMiss++
        if ($hit) { $wrongHits++ } 
    }
    
    $icon = if ($passed) { "PASS" } else { "FAIL" }
    Write-Host "$icon $actual (stage=$stage) expect=$($t.expect) - `"$($t.q)`"" -ForegroundColor $(if ($passed) { "Green" } else { "Red" })
}

# Cleanup
Remove-Item test_body_*.json -ErrorAction SilentlyContinue

$hitRate = if ($shouldHit -gt 0) { [math]::Round(($hitCount / $shouldHit) * 100, 1) } else { 0 }
$wrongHitRate = if ($shouldMiss -gt 0) { [math]::Round(($wrongHits / $shouldMiss) * 100, 1) } else { 0 }

Write-Host ""
Write-Host "=== RESULTS ===" -ForegroundColor Cyan
Write-Host "Hit rate: $hitCount/$shouldHit ($hitRate%) - target >= 85%" -ForegroundColor $(if ($hitRate -ge 85) { "Green" } else { "Red" })
Write-Host "Wrong-hit rate: $wrongHits/$shouldMiss ($wrongHitRate%) - target = 0%" -ForegroundColor $(if ($wrongHitRate -eq 0) { "Green" } else { "Red" })

if ($hitRate -ge 85 -and $wrongHitRate -eq 0) {
    Write-Host ""
    Write-Host "ALL TARGETS MET!" -ForegroundColor Green
} elseif ($hitRate -ge 85 -and $wrongHitRate -le 10) {
    Write-Host ""
    Write-Host "Close - hit rate good, wrong-hit rate needs work" -ForegroundColor Yellow
}

