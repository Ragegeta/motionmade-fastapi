$apiUrl = "https://motionmade-fastapi.onrender.com"

$tests = @(
    # Should HIT - cleaning queries
    @{q="how much for a cleaner"; expect="hit"},
    @{q="do u do end of lease"; expect="hit"},
    @{q="hw much 4 house clean"; expect="hit"},
    @{q="wat areas u service"; expect="hit"},
    @{q="cn u come 2morrow"; expect="hit"},
    @{q="r u insured"; expect="hit"},
    @{q="bond back guarantee"; expect="hit"},
    @{q="office cleaning prices"; expect="hit"},
    
    # Should MISS - wrong services for cleaner
    @{q="can u fix my powerpoint"; expect="miss"},
    @{q="need a plumber"; expect="miss"},
    @{q="gas heater broken"; expect="miss"},
    @{q="can u mow my lawn"; expect="miss"},
    @{q="paint my house"; expect="miss"}
)

$hitCount = 0; $shouldHit = 0; $wrongHits = 0; $shouldMiss = 0

Write-Host "`n=== BRISSY_CLEANERS TEST ===" -ForegroundColor Cyan

foreach ($t in $tests) {
    $body = "{`"tenantId`":`"brissy_cleaners`",`"customerMessage`":`"$($t.q)`"}"
    $response = curl.exe -s -i -X POST "$apiUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" -d $body 2>&1 | Out-String
    
    $hit = $response -match "x-faq-hit:\s*true"
    if ($response -match "x-retrieval-stage:\s*([^\r\n]+)") {
        $stage = $Matches[1].Trim()
    } else {
        $stage = "?"
    }
    if ($response -match "x-timing-total:\s*(\d+)") {
        $latency = [math]::Round([int]$Matches[1]/1000, 2)
    } else {
        $latency = "?"
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
    Write-Host "$icon $actual (${latency}s, stage=$stage) expect=$($t.expect) - `"$($t.q)`"" -ForegroundColor $(if ($passed) { "Green" } else { "Red" })
}

$hitRate = if ($shouldHit -gt 0) { [math]::Round(($hitCount / $shouldHit) * 100, 1) } else { 0 }
$wrongHitRate = if ($shouldMiss -gt 0) { [math]::Round(($wrongHits / $shouldMiss) * 100, 1) } else { 0 }

Write-Host "`n=== RESULTS ===" -ForegroundColor Cyan
Write-Host "Hit rate: $hitCount/$shouldHit ($hitRate%) - target >= 85%" -ForegroundColor $(if ($hitRate -ge 85) { "Green" } else { "Red" })
Write-Host "Wrong-hit rate: $wrongHits/$shouldMiss ($wrongHitRate%) - target = 0%" -ForegroundColor $(if ($wrongHitRate -eq 0) { "Green" } else { "Red" })

if ($hitRate -ge 85 -and $wrongHitRate -eq 0) {
    Write-Host "`nSYSTEM IS REPLICABLE" -ForegroundColor Green
} else {
    Write-Host "`nNEEDS WORK - check failures above" -ForegroundColor Red
}
