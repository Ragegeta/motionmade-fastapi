$apiUrl = "https://api.motionmadebne.com.au"

# Load sparkys testpack
$sparkysTests = @()
if (Test-Path "tests\sparkys_electrical.json") {
    $sparkysData = Get-Content "tests\sparkys_electrical.json" | ConvertFrom-Json
    foreach ($test in $sparkysData.tests) {
        $sparkysTests += @{
            tenant = "sparkys_electrical"
            q = $test.question
            expect = if ($test.expect_faq_hit) { "hit" } else { "miss" }
            name = $test.name
        }
    }
}

# brissy_cleaners comprehensive tests
$brissyTests = @(
    @{tenant="brissy_cleaners"; q="how much for cleaning"; expect="hit"; name="Pricing"},
    @{tenant="brissy_cleaners"; q="do u do end of lease"; expect="hit"; name="Services"},
    @{tenant="brissy_cleaners"; q="hw much 4 house clean"; expect="hit"; name="Pricing messy"},
    @{tenant="brissy_cleaners"; q="wat areas u service"; expect="hit"; name="Area messy"},
    @{tenant="brissy_cleaners"; q="r u insured"; expect="hit"; name="Insurance"},
    @{tenant="brissy_cleaners"; q="bond back guarantee"; expect="hit"; name="Guarantee"},
    @{tenant="brissy_cleaners"; q="need an electrician"; expect="miss"; name="Wrong service 1"},
    @{tenant="brissy_cleaners"; q="can u fix my powerpoint"; expect="miss"; name="Wrong service 2"},
    @{tenant="brissy_cleaners"; q="need a plumber"; expect="miss"; name="Wrong service 3"},
    @{tenant="brissy_cleaners"; q="paint my house"; expect="miss"; name="Wrong service 4"}
)

Write-Host "`n=== COMPREHENSIVE TEST: sparkys_electrical ===" -ForegroundColor Cyan
Write-Host "Running $($sparkysTests.Count) tests from testpack`n"

$sparkysPass = 0; $sparkysTotal = 0; $sparkysLatencies = @()
foreach ($t in $sparkysTests) {
    $body = "{`"tenantId`":`"$($t.tenant)`",`"customerMessage`":`"$($t.q)`"}"
    $body | Out-File -FilePath temp_body.json -Encoding UTF8 -NoNewline
    $start = Get-Date
    $r = curl.exe -s -i -X POST "$apiUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" -d "@temp_body.json" 2>&1 | Out-String
    $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds, 2)
    Remove-Item temp_body.json -ErrorAction SilentlyContinue
    
    $hit = $r -match "x-faq-hit:\s*true"
    $latency = if ($r -match "x-timing-total:\s*(\d+)") { [math]::Round([int]$Matches[1]/1000, 2) } else { $elapsed }
    if ($latency -ne "?") { $sparkysLatencies += $latency }
    
    $actual = if ($hit) { "HIT" } else { "MISS" }
    $passed = ($hit -and $t.expect -eq "hit") -or (-not $hit -and $t.expect -eq "miss")
    $sparkysTotal++; if ($passed) { $sparkysPass++ }
    
    $icon = if ($passed) { "PASS" } else { "FAIL" }
    Write-Host "$icon $actual (${latency}s) - $($t.name): `"$($t.q)`"" -ForegroundColor $(if ($passed) { "Green" } else { "Red" })
}

$sparkysAvgLatency = if ($sparkysLatencies.Count -gt 0) { [math]::Round(($sparkysLatencies | Measure-Object -Average).Average, 2) } else { "?" }
$sparkysMaxLatency = if ($sparkysLatencies.Count -gt 0) { [math]::Round(($sparkysLatencies | Measure-Object -Maximum).Maximum, 2) } else { "?" }

Write-Host "`n=== COMPREHENSIVE TEST: brissy_cleaners ===" -ForegroundColor Cyan
Write-Host "Running $($brissyTests.Count) tests`n"

$brissyPass = 0; $brissyTotal = 0; $brissyLatencies = @()
foreach ($t in $brissyTests) {
    $body = "{`"tenantId`":`"$($t.tenant)`",`"customerMessage`":`"$($t.q)`"}"
    $body | Out-File -FilePath temp_body.json -Encoding UTF8 -NoNewline
    $start = Get-Date
    $r = curl.exe -s -i -X POST "$apiUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" -d "@temp_body.json" 2>&1 | Out-String
    $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds, 2)
    Remove-Item temp_body.json -ErrorAction SilentlyContinue
    
    $hit = $r -match "x-faq-hit:\s*true"
    $latency = if ($r -match "x-timing-total:\s*(\d+)") { [math]::Round([int]$Matches[1]/1000, 2) } else { $elapsed }
    if ($latency -ne "?") { $brissyLatencies += $latency }
    
    $actual = if ($hit) { "HIT" } else { "MISS" }
    $passed = ($hit -and $t.expect -eq "hit") -or (-not $hit -and $t.expect -eq "miss")
    $brissyTotal++; if ($passed) { $brissyPass++ }
    
    $icon = if ($passed) { "PASS" } else { "FAIL" }
    Write-Host "$icon $actual (${latency}s) - $($t.name): `"$($t.q)`"" -ForegroundColor $(if ($passed) { "Green" } else { "Red" })
}

$brissyAvgLatency = if ($brissyLatencies.Count -gt 0) { [math]::Round(($brissyLatencies | Measure-Object -Average).Average, 2) } else { "?" }
$brissyMaxLatency = if ($brissyLatencies.Count -gt 0) { [math]::Round(($brissyLatencies | Measure-Object -Maximum).Maximum, 2) } else { "?" }

Write-Host "`n=== FINAL SUMMARY ===" -ForegroundColor Cyan
Write-Host "sparkys_electrical:" -ForegroundColor White
Write-Host "  Pass rate: $sparkysPass/$sparkysTotal ([math]::Round($sparkysPass/$sparkysTotal*100, 1)%)" -ForegroundColor $(if ($sparkysPass -eq $sparkysTotal) { "Green" } else { "Yellow" })
Write-Host "  Avg latency: ${sparkysAvgLatency}s (max: ${sparkysMaxLatency}s)" -ForegroundColor $(if ($sparkysAvgLatency -ne "?" -and $sparkysAvgLatency -lt 3) { "Green" } else { "Yellow" })
Write-Host "brissy_cleaners:" -ForegroundColor White
Write-Host "  Pass rate: $brissyPass/$brissyTotal ([math]::Round($brissyPass/$brissyTotal*100, 1)%)" -ForegroundColor $(if ($brissyPass -eq $brissyTotal) { "Green" } else { "Yellow" })
Write-Host "  Avg latency: ${brissyAvgLatency}s (max: ${brissyMaxLatency}s)" -ForegroundColor $(if ($brissyAvgLatency -ne "?" -and $brissyAvgLatency -lt 3) { "Green" } else { "Yellow" })

if ($sparkysPass -eq $sparkysTotal -and $brissyPass -eq $brissyTotal -and $sparkysAvgLatency -lt 3 -and $brissyAvgLatency -lt 3) {
    Write-Host "`nALL TESTS PASSED - HIGH STANDARD VERIFIED" -ForegroundColor Green
} else {
    Write-Host "`nSOME ISSUES FOUND" -ForegroundColor Yellow
}


