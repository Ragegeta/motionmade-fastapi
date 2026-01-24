# smoke_test.ps1 - Quick health check for all tenants
cd C:\MM\motionmade-fastapi

Write-Host "=== MOTIONMADE SMOKE TEST ===" -ForegroundColor Cyan

# Warm up Render
Write-Host "Warming up Render..." -ForegroundColor Yellow
try {
    $null = Invoke-WebRequest -Uri "https://api.motionmadebne.com.au/api/health" -UseBasicParsing -TimeoutSec 60
    Write-Host "Render is awake" -ForegroundColor Green
} catch {
    Write-Host "Warm-up failed (may be cold starting): $_" -ForegroundColor Yellow
}

Start-Sleep -Seconds 2

# Test tenants
$tests = @(
    @{tenant="sparkys_electrical"; q="how much for a powerpoint"; expect="hit"},
    @{tenant="brissy_cleaners"; q="how much for end of lease"; expect="hit"},
    @{tenant="motionmade_demo"; q="what do you do"; expect="hit"}
)

$passed = 0
$failed = 0

foreach ($t in $tests) {
    $body = @{tenantId=$t.tenant; customerMessage=$t.q} | ConvertTo-Json
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    
    try {
        $response = Invoke-WebRequest -Uri "https://api.motionmadebne.com.au/api/v2/generate-quote-reply" `
            -Method POST `
            -Headers @{"Content-Type"="application/json"} `
            -Body $body `
            -UseBasicParsing `
            -TimeoutSec 120
        
        $sw.Stop()
        $latency = [math]::Round($sw.Elapsed.TotalSeconds, 2)
        
        $hit = $response.Headers["x-faq-hit"] -eq "true"
        $stage = $response.Headers["x-retrieval-stage"]
        $faqCount = $response.Headers["x-tenant-faq-count"]
        
        $status = if ($hit) { "HIT" } else { "MISS" }
        $icon = if ($hit -eq ($t.expect -eq "hit")) { "âœ…"; $passed++ } else { "âŒ"; $failed++ }
        
        Write-Host "$icon $($t.tenant): $status | ${latency}s | stage=$stage | faqs=$faqCount" -ForegroundColor $(if ($hit) { "Green" } else { "Red" })
    } catch {
        $failed++
        Write-Host "âŒ $($t.tenant): ERROR - $_" -ForegroundColor Red
    }
}

Write-Host "`n=== RESULTS ===" -ForegroundColor Cyan
Write-Host "Passed: $passed / $($passed + $failed)" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Yellow" })
