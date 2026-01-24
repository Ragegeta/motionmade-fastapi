$apiUrl = "https://api.motionmadebne.com.au"

$tests = @(
    @{q="can u fix my powerpoint"; expect="miss"},
    @{q="paint my house"; expect="miss"},
    @{q="need a plumber"; expect="miss"},
    @{q="gas heater broken"; expect="miss"},
    @{q="can u mow my lawn"; expect="miss"},
    @{q="i need a sparky"; expect="miss"},
    @{q="electrician needed"; expect="miss"}
)

$wrongHits = 0
Write-Host "`n=== WRONG-SERVICE RE-TEST ===" -ForegroundColor Cyan

foreach ($t in $tests) {
    $body = "{`"tenantId`":`"brissy_cleaners`",`"customerMessage`":`"$($t.q)`"}"
    $body | Out-File -FilePath temp_body.json -Encoding UTF8 -NoNewline
    $response = curl.exe -s -i -X POST "$apiUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" -d "@temp_body.json" 2>&1 | Out-String
    Remove-Item temp_body.json -ErrorAction SilentlyContinue
    
    $hit = $response -match "x-faq-hit:\s*true"
    if ($hit) { $wrongHits++ }
    
    $icon = if (-not $hit) { "PASS" } else { "FAIL" }
    $actual = if ($hit) { "HIT (BAD)" } else { "MISS (GOOD)" }
    Write-Host "$icon $actual - `"$($t.q)`"" -ForegroundColor $(if (-not $hit) { "Green" } else { "Red" })
}

$wrongHitRate = [math]::Round(($wrongHits / $tests.Count) * 100, 1)
Write-Host "`nWrong-hit rate: $wrongHits/$($tests.Count) ($wrongHitRate%) - target = 0%" -ForegroundColor $(if ($wrongHitRate -eq 0) { "Green" } else { "Red" })

if ($wrongHitRate -eq 0) {
    Write-Host "`nWRONG-SERVICE FIX VERIFIED" -ForegroundColor Green
} else {
    Write-Host "`nSTILL FAILING - check which queries" -ForegroundColor Red
}


