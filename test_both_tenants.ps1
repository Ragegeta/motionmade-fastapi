$apiUrl = "https://api.motionmadebne.com.au"

Write-Host "`n=== SMOKE TEST: sparkys_electrical ===" -ForegroundColor Cyan
$tests = @(
    @{tenant="sparkys_electrical"; q="how much for a sparky"; expect="hit"},
    @{tenant="sparkys_electrical"; q="do u do safety switches"; expect="hit"},
    @{tenant="sparkys_electrical"; q="need a plumber"; expect="miss"},
    @{tenant="sparkys_electrical"; q="can u clean my house"; expect="miss"}
)

$sparkysPass = 0; $sparkysTotal = 0
foreach ($t in $tests) {
    $body = "{`"tenantId`":`"$($t.tenant)`",`"customerMessage`":`"$($t.q)`"}"
    $body | Out-File -FilePath temp_body.json -Encoding UTF8 -NoNewline
    $r = curl.exe -s -i -X POST "$apiUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" -d "@temp_body.json" 2>&1 | Out-String
    Remove-Item temp_body.json -ErrorAction SilentlyContinue
    
    $hit = $r -match "x-faq-hit:\s*true"
    $latency = if ($r -match "x-timing-total:\s*(\d+)") { [math]::Round([int]$Matches[1]/1000, 2) } else { "?" }
    $actual = if ($hit) { "HIT" } else { "MISS" }
    $passed = ($hit -and $t.expect -eq "hit") -or (-not $hit -and $t.expect -eq "miss")
    $sparkysTotal++; if ($passed) { $sparkysPass++ }
    
    $icon = if ($passed) { "PASS" } else { "FAIL" }
    $latencyColor = if ($latency -ne "?" -and $latency -lt 3) { "Green" } elseif ($latency -ne "?" -and $latency -lt 6) { "Yellow" } else { "Red" }
    Write-Host "$icon $actual (${latency}s) - `"$($t.q)`"" -ForegroundColor $(if ($passed) { "Green" } else { "Red" })
    if ($latency -ne "?" -and $latency -ge 3) {
        Write-Host "  WARNING: Latency ${latency}s exceeds 3s target" -ForegroundColor Yellow
    }
}

Write-Host "`n=== SMOKE TEST: brissy_cleaners ===" -ForegroundColor Cyan
$tests2 = @(
    @{tenant="brissy_cleaners"; q="how much for cleaning"; expect="hit"},
    @{tenant="brissy_cleaners"; q="do u do end of lease"; expect="hit"},
    @{tenant="brissy_cleaners"; q="need an electrician"; expect="miss"},
    @{tenant="brissy_cleaners"; q="can u fix my powerpoint"; expect="miss"}
)

$brissyPass = 0; $brissyTotal = 0
foreach ($t in $tests2) {
    $body = "{`"tenantId`":`"$($t.tenant)`",`"customerMessage`":`"$($t.q)`"}"
    $body | Out-File -FilePath temp_body.json -Encoding UTF8 -NoNewline
    $r = curl.exe -s -i -X POST "$apiUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" -d "@temp_body.json" 2>&1 | Out-String
    Remove-Item temp_body.json -ErrorAction SilentlyContinue
    
    $hit = $r -match "x-faq-hit:\s*true"
    $latency = if ($r -match "x-timing-total:\s*(\d+)") { [math]::Round([int]$Matches[1]/1000, 2) } else { "?" }
    $actual = if ($hit) { "HIT" } else { "MISS" }
    $passed = ($hit -and $t.expect -eq "hit") -or (-not $hit -and $t.expect -eq "miss")
    $brissyTotal++; if ($passed) { $brissyPass++ }
    
    $icon = if ($passed) { "PASS" } else { "FAIL" }
    $latencyColor = if ($latency -ne "?" -and $latency -lt 3) { "Green" } elseif ($latency -ne "?" -and $latency -lt 6) { "Yellow" } else { "Red" }
    Write-Host "$icon $actual (${latency}s) - `"$($t.q)`"" -ForegroundColor $(if ($passed) { "Green" } else { "Red" })
    if ($latency -ne "?" -and $latency -ge 3) {
        Write-Host "  WARNING: Latency ${latency}s exceeds 3s target" -ForegroundColor Yellow
    }
}

Write-Host "`n=== SUMMARY ===" -ForegroundColor Cyan
Write-Host "sparkys_electrical: $sparkysPass/$sparkysTotal passed" -ForegroundColor $(if ($sparkysPass -eq $sparkysTotal) { "Green" } else { "Red" })
Write-Host "brissy_cleaners: $brissyPass/$brissyTotal passed" -ForegroundColor $(if ($brissyPass -eq $brissyTotal) { "Green" } else { "Red" })

if ($sparkysPass -eq $sparkysTotal -and $brissyPass -eq $brissyTotal) {
    Write-Host "`nALL TESTS PASSED" -ForegroundColor Green
} else {
    Write-Host "`nSOME TESTS FAILED" -ForegroundColor Red
}


