$apiUrl = "https://api.motionmadebne.com.au"

$tests = @(
    # Should HIT
    @{q="how much for a cleaner"; expect="hit"},
    @{q="do u do end of lease"; expect="hit"},
    @{q="hw much 4 house clean"; expect="hit"},
    @{q="wat areas u service"; expect="hit"},
    @{q="cn u come 2morrow"; expect="hit"},
    @{q="r u insured"; expect="hit"},
    @{q="bond back guarantee"; expect="hit"},
    @{q="office cleaning prices"; expect="hit"},
    # Should MISS
    @{q="can u fix my powerpoint"; expect="miss"},
    @{q="paint my house"; expect="miss"},
    @{q="need a plumber"; expect="miss"},
    @{q="gas heater broken"; expect="miss"},
    @{q="can u mow my lawn"; expect="miss"},
    @{q="i need a sparky"; expect="miss"},
    @{q="electrician needed"; expect="miss"}
)

$hitCount = 0; $shouldHit = 0; $wrongHits = 0; $shouldMiss = 0

Write-Host "`n=== BRISSY_CLEANERS FINAL TEST ===" -ForegroundColor Cyan

foreach ($t in $tests) {
    $body = "{`"tenantId`":`"brissy_cleaners`",`"customerMessage`":`"$($t.q)`"}"
    $body | Out-File -FilePath temp_body.json -Encoding UTF8 -NoNewline
    $r = curl.exe -s -i -X POST "$apiUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" -d "@temp_body.json" 2>&1 | Out-String
    Remove-Item temp_body.json -ErrorAction SilentlyContinue
    
    $hit = $r -match "x-faq-hit:\s*true"
    
    if ($t.expect -eq "hit") { $shouldHit++; if ($hit) { $hitCount++ } }
    if ($t.expect -eq "miss") { $shouldMiss++; if ($hit) { $wrongHits++ } }
    
    $icon = if (($hit -and $t.expect -eq "hit") -or (-not $hit -and $t.expect -eq "miss")) { "PASS" } else { "FAIL" }
    $actual = if ($hit) { "HIT" } else { "MISS" }
    Write-Host "$icon $actual expect=$($t.expect) - `"$($t.q)`"" -ForegroundColor $(if ($icon -eq "PASS") { "Green" } else { "Red" })
}

$hitRate = if ($shouldHit -gt 0) { [math]::Round(($hitCount / $shouldHit) * 100, 1) } else { 0 }
$wrongHitRate = if ($shouldMiss -gt 0) { [math]::Round(($wrongHits / $shouldMiss) * 100, 1) } else { 0 }

Write-Host "`n=== FINAL RESULTS ===" -ForegroundColor Cyan
Write-Host "Hit rate: $hitCount/$shouldHit ($hitRate%) - target >= 85%" -ForegroundColor $(if ($hitRate -ge 85) { "Green" } else { "Red" })
Write-Host "Wrong-hit rate: $wrongHits/$shouldMiss ($wrongHitRate%) - target = 0%" -ForegroundColor $(if ($wrongHitRate -eq 0) { "Green" } else { "Red" })

if ($hitRate -ge 85 -and $wrongHitRate -eq 0) {
    Write-Host "`nPHASE 2 COMPLETE - SYSTEM IS REPLICABLE" -ForegroundColor Green
} else {
    Write-Host "`nPhase 2 incomplete - needs work" -ForegroundColor Yellow
}


