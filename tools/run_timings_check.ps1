# Timings check script - verifies debug timing headers are working
# Usage: .\tools\run_timings_check.ps1

$ErrorActionPreference = "Stop"

# 1) cd to C:\MM\motionmade-fastapi
Set-Location "C:\MM\motionmade-fastapi"

Write-Host "`n=== TIMINGS CHECK ===" -ForegroundColor Cyan
Write-Host "Working directory: $(Get-Location)" -ForegroundColor Gray

# 2) Load ADMIN_TOKEN from .env into $env:ADMIN_TOKEN
$envFile = Join-Path (Get-Location) ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "Error: .env file not found at $envFile" -ForegroundColor Red
    exit 1
}

$adminToken = (Get-Content $envFile | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
if (-not $adminToken) {
    Write-Host "Error: ADMIN_TOKEN not found in .env" -ForegroundColor Red
    exit 1
}

$env:ADMIN_TOKEN = $adminToken
Write-Host "ADMIN_TOKEN loaded" -ForegroundColor Green

# 3) Print Render /api/health (so we see the deployed SHA)
Write-Host "`n=== RENDER HEALTH ===" -ForegroundColor Cyan
try {
    $health = Invoke-RestMethod -Uri "https://motionmade-fastapi.onrender.com/api/health" -Method GET -TimeoutSec 30
    Write-Host "Status: OK" -ForegroundColor Green
    Write-Host "Git SHA: $($health.gitSha)" -ForegroundColor Yellow
    Write-Host "Release: $($health.release)" -ForegroundColor Gray
    Write-Host "Deployed: $($health.deployed)" -ForegroundColor Gray
} catch {
    Write-Host "Error fetching health: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# 4) Create tmp_body.json
$tmpBodyPath = Join-Path (Get-Location) "tmp_body.json"
$bodyContent = @{
    tenantId = "sparkys_electrical"
    customerMessage = "how much do you charge"
} | ConvertTo-Json -Compress

$bodyContent | Out-File -FilePath $tmpBodyPath -Encoding UTF8 -NoNewline
Write-Host "`n=== CREATED tmp_body.json ===" -ForegroundColor Cyan
Write-Host "Content: $bodyContent" -ForegroundColor Gray

# 5) Send ONE request with curl.exe and print specific headers
Write-Host "`n=== CURL REQUEST ===" -ForegroundColor Cyan
$url = "https://motionmade-fastapi.onrender.com/api/v2/generate-quote-reply"

# Use curl.exe with --data-binary
$curlOutput = & curl.exe -s -i `
    -X POST `
    -H "Content-Type: application/json" `
    -H "X-Debug-Timings: 1" `
    -H "Authorization: Bearer $env:ADMIN_TOKEN" `
    --data-binary "@$tmpBodyPath" `
    $url

# Parse output to extract only the headers we care about
$lines = $curlOutput -split "`n"
$statusLine = $null
$relevantHeaders = @{}

foreach ($line in $lines) {
    $line = $line.Trim()
    
    # Capture HTTP status line
    if ($line -match "^HTTP/") {
        $statusLine = $line
        continue
    }
    
    # Skip empty line (separator between headers and body)
    if ([string]::IsNullOrWhiteSpace($line)) {
        break
    }
    
    # Parse header
    if ($line -match "^([^:]+):\s*(.+)$") {
        $headerName = $matches[1].Trim().ToLower()
        $headerValue = $matches[2].Trim()
        
        # Only capture headers we care about
        if ($headerName -eq "x-debug-timing-gate" -or
            $headerName -like "x-timing-*" -or
            $headerName -eq "x-retrieval-stage" -or
            $headerName -eq "x-faq-hit" -or
            $headerName -eq "x-candidate-count") {
            $relevantHeaders[$headerName] = $headerValue
        }
    }
}

# Print results
Write-Host "`n=== RESPONSE HEADERS ===" -ForegroundColor Cyan
if ($statusLine) {
    Write-Host $statusLine -ForegroundColor Yellow
}

# Print x-debug-timing-gate
if ($relevantHeaders.ContainsKey("x-debug-timing-gate")) {
    Write-Host "x-debug-timing-gate: $($relevantHeaders['x-debug-timing-gate'])" -ForegroundColor $(if ($relevantHeaders['x-debug-timing-gate'] -eq "ok") { "Green" } else { "Yellow" })
} else {
    Write-Host "x-debug-timing-gate: (missing)" -ForegroundColor Red
}

# Print all x-timing-* headers
$timingHeaders = $relevantHeaders.Keys | Where-Object { $_ -like "x-timing-*" }
if ($timingHeaders.Count -gt 0) {
    Write-Host "`nx-timing-* headers:" -ForegroundColor Cyan
    foreach ($header in $timingHeaders | Sort-Object) {
        Write-Host "  $header`: $($relevantHeaders[$header])" -ForegroundColor Green
    }
} else {
    Write-Host "`nx-timing-* headers: (none found)" -ForegroundColor Red
}

# Print other headers
if ($relevantHeaders.ContainsKey("x-retrieval-stage")) {
    Write-Host "x-retrieval-stage: $($relevantHeaders['x-retrieval-stage'])" -ForegroundColor Gray
}
if ($relevantHeaders.ContainsKey("x-faq-hit")) {
    Write-Host "x-faq-hit: $($relevantHeaders['x-faq-hit'])" -ForegroundColor Gray
}
if ($relevantHeaders.ContainsKey("x-candidate-count")) {
    Write-Host "x-candidate-count: $($relevantHeaders['x-candidate-count'])" -ForegroundColor Gray
}

# 6) Run the diagnostic confidence pack
Write-Host "`n=== RUNNING DIAGNOSTIC CONFIDENCE PACK ===" -ForegroundColor Cyan
$testPackPath = ".\tools\testpacks\sparkys_electrical_diagnostic_pack.json"

# Check if test pack exists
if (-not (Test-Path $testPackPath)) {
    Write-Host "Warning: Test pack not found at $testPackPath" -ForegroundColor Yellow
    Write-Host "Creating default diagnostic pack..." -ForegroundColor Yellow
    
    $testPackDir = Split-Path $testPackPath -Parent
    if (-not (Test-Path $testPackDir)) {
        New-Item -ItemType Directory -Path $testPackDir -Force | Out-Null
    }
    
    $defaultPack = @{
        should_hit = @("how much do you charge", "ur prices pls", "what's your call out fee", "how much", "cost", "price", "rates")
        should_miss = @("do you do plumbing", "can you paint my house", "do you do roofing", "can you fix my car", "do you do tiling", "landscaping services")
        edge_unclear = @("help", "???", "hi", "hello")
    } | ConvertTo-Json -Depth 10
    
    $defaultPack | Out-File -FilePath $testPackPath -Encoding UTF8
    Write-Host "Created default pack at $testPackPath" -ForegroundColor Green
}

& .\tools\run_confidence_pack.ps1 `
    -TenantId "sparkys_electrical" `
    -Runs 1 `
    -AdminBase "https://motionmade-fastapi.onrender.com" `
    -PublicBase "https://motionmade-fastapi.onrender.com" `
    -TestPackPath $testPackPath `
    -DebugTimings `
    -MaxCases 13

# 7) Find newest results JSON and print specific metrics
Write-Host "`n=== RESULTS SUMMARY ===" -ForegroundColor Cyan
$resultsDir = Join-Path (Get-Location) "tools\results"
if (-not (Test-Path $resultsDir)) {
    Write-Host "Error: Results directory not found at $resultsDir" -ForegroundColor Red
    exit 1
}

$resultFiles = Get-ChildItem -Path $resultsDir -Filter "confidence_sparkys_electrical_*.json" | Sort-Object LastWriteTime -Descending
if ($resultFiles.Count -eq 0) {
    Write-Host "Error: No results JSON files found" -ForegroundColor Red
    exit 1
}

$newestResult = $resultFiles[0]
Write-Host "Newest results JSON: $($newestResult.FullName)" -ForegroundColor Yellow

try {
    $results = Get-Content $newestResult.FullName | ConvertFrom-Json
    
    # Print requested metrics
    Write-Host "`n=== METRICS ===" -ForegroundColor Cyan
    
    # HTTP latency (check different possible field names)
    if ($results.summary_metrics.http_latency) {
        if ($results.summary_metrics.http_latency.p50_mean_ms) {
            Write-Host "HTTP Latency p50: $($results.summary_metrics.http_latency.p50_mean_ms) ms" -ForegroundColor Green
        }
        if ($results.summary_metrics.http_latency.p95_mean_ms) {
            Write-Host "HTTP Latency p95: $($results.summary_metrics.http_latency.p95_mean_ms) ms" -ForegroundColor Green
        }
    }
    
    # Check for alternative field names
    if ($results.summary_metrics.http_latency_p50_ms) {
        Write-Host "HTTP Latency p50: $($results.summary_metrics.http_latency_p50_ms) ms" -ForegroundColor Green
    }
    if ($results.summary_metrics.http_latency_p95_ms) {
        Write-Host "HTTP Latency p95: $($results.summary_metrics.http_latency_p95_ms) ms" -ForegroundColor Green
    }
    
    # Timing headers present cases (count results with timing_total_ms)
    $timingHeadersPresent = ($results.results | Where-Object { $null -ne $_.timing_total_ms }).Count
    Write-Host "Timing headers present cases: $timingHeadersPresent / $($results.results.Count)" -ForegroundColor $(if ($timingHeadersPresent -gt 0) { "Green" } else { "Red" })
    
    # Selector called cases
    $selectorCalledCases = ($results.results | Where-Object { 
        $val = $_.selector_called
        $null -ne $val -and ($val -is [bool] -and $val -eq $true)
    }).Count
    Write-Host "Selector called cases: $selectorCalledCases / $($results.results.Count)" -ForegroundColor Gray
    
} catch {
    Write-Host "Error parsing results JSON: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}

# Cleanup
if (Test-Path $tmpBodyPath) {
    Remove-Item $tmpBodyPath -Force
    Write-Host "`nCleaned up tmp_body.json" -ForegroundColor Gray
}

Write-Host "`n=== DONE ===" -ForegroundColor Cyan

