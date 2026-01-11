# Test FTS OR fix on production
$apiUrl = "https://api.motionmadebne.com.au"

# Test queries
$tests = @(
    "smoke alarm beeping",
    "powerpoint broken",
    "circuit breaker tripping",
    "lights flickering",
    "how much to install a fan",
    "urgent no power",
    "circuit breaker keeps tripping",
    "outlet not working",
    "smoke detector beeping",
    "light switch broken"
)

Write-Host "=== FTS OR FIX - END-TO-END TEST ===" -ForegroundColor Cyan
Write-Host "API: $apiUrl" -ForegroundColor Gray
Write-Host "Tenant: sparkys_electrical" -ForegroundColor Gray
Write-Host ""

$results = @()

foreach ($q in $tests) {
    $body = @{tenantId="sparkys_electrical"; customerMessage=$q} | ConvertTo-Json -Compress
    $start = Get-Date
    
    # Use temp file to avoid PowerShell encoding issues with curl.exe -d
    $tempFile = [System.IO.Path]::GetTempFileName()
    try {
        $body | Out-File -FilePath $tempFile -Encoding utf8 -NoNewline
        $r = (curl.exe -s -i -X POST "$apiUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" -d "@$tempFile" 2>&1) | Out-String
    } finally {
        Remove-Item $tempFile -ErrorAction SilentlyContinue
    }
    
    $elapsed = [math]::Round(((Get-Date) - $start).TotalSeconds, 2)
    
    $hit = $r -match "x-faq-hit:\s*true"
    $ftsCount = if ($r -match "x-fts-count:\s*(\d+)") { [int]$Matches[1] } else { 0 }
    $vectorCount = if ($r -match "x-vector-count:\s*(\d+)") { [int]$Matches[1] } else { 0 }
    $stage = if ($r -match "x-retrieval-stage:\s*(\S+)") { $Matches[1] } else { "?" }
    $score = if ($r -match "x-retrieval-score:\s*([\d.]+)") { [float]$Matches[1] } else { 0 }
    
    $result = if ($hit) { "HIT" } else { "MISS" }
    $color = if ($hit) { "Green" } else { "Yellow" }
    
    $resultObj = [PSCustomObject]@{
        Query = $q
        Result = $result
        Latency = $elapsed
        FTS_Count = $ftsCount
        Vector_Count = $vectorCount
        Stage = $stage
        Score = $score
    }
    $results += $resultObj
    
    Write-Host ""
    Write-Host "  $result - $q" -ForegroundColor $color
    Write-Host "    Time: ${elapsed}s | FTS: $ftsCount | Vector: $vectorCount | Stage: $stage | Score: $score" -ForegroundColor Gray
}

Write-Host ""
Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
Write-Host ""

$totalQueries = $results.Count
$hits = ($results | Where-Object { $_.Result -eq "HIT" }).Count
$misses = ($results | Where-Object { $_.Result -eq "MISS" }).Count
$queriesWithFTS = ($results | Where-Object { $_.FTS_Count -gt 0 }).Count
$avgLatency = [math]::Round(($results | Measure-Object -Property Latency -Average).Average, 2)
$maxLatency = [math]::Round(($results | Measure-Object -Property Latency -Maximum).Maximum, 2)
$minLatency = [math]::Round(($results | Measure-Object -Property Latency -Minimum).Minimum, 2)

Write-Host "Total Queries: $totalQueries" -ForegroundColor White
Write-Host "Hits: $hits ($([math]::Round($hits/$totalQueries*100, 1))%)" -ForegroundColor Green
Write-Host "Misses: $misses ($([math]::Round($misses/$totalQueries*100, 1))%)" -ForegroundColor Yellow
Write-Host "Queries with FTS matches: $queriesWithFTS ($([math]::Round($queriesWithFTS/$totalQueries*100, 1))%)" -ForegroundColor Cyan
Write-Host "Average Latency: ${avgLatency}s" -ForegroundColor White
Write-Host "Latency Range: ${minLatency}s - ${maxLatency}s" -ForegroundColor Gray
Write-Host ""

# Key check: smoke alarm beeping
$smokeAlarm = $results | Where-Object { $_.Query -eq "smoke alarm beeping" }
if ($smokeAlarm) {
    Write-Host "=== KEY CHECK: 'smoke alarm beeping' ===" -ForegroundColor Cyan
    Write-Host "FTS Count: $($smokeAlarm.FTS_Count)" -ForegroundColor $(if ($smokeAlarm.FTS_Count -gt 0) { "Green" } else { "Red" })
    Write-Host "Result: $($smokeAlarm.Result)" -ForegroundColor $(if ($smokeAlarm.Result -eq "HIT") { "Green" } else { "Yellow" })
    Write-Host "Latency: $($smokeAlarm.Latency)s" -ForegroundColor White
    Write-Host ""
    if ($smokeAlarm.FTS_Count -gt 0) {
        Write-Host "[FIXED] 'smoke alarm beeping' now has FTS matches (was 0 before)" -ForegroundColor Green
    } else {
        Write-Host "[ISSUE] 'smoke alarm beeping' still has 0 FTS matches" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== DETAILED RESULTS ===" -ForegroundColor Cyan
$results | Format-Table -AutoSize

