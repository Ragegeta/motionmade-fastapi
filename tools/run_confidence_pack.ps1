param(
    [Parameter(Mandatory=$true)]
    [string]$TenantId,
    
    [Parameter(Mandatory=$false)]
    [int]$Runs = 5,
    
    [Parameter(Mandatory=$false)]
    [string]$AdminBase = "https://motionmade-fastapi.onrender.com",
    
    [Parameter(Mandatory=$false)]
    [string]$PublicBase = "https://api.motionmadebne.com.au",
    
    [Parameter(Mandatory=$false)]
    [switch]$ScaleTest = $false,
    
    [Parameter(Mandatory=$false)]
    [string]$TestPackPath = $null
)

$ErrorActionPreference = "Stop"

# Get admin token
$envFile = Join-Path $PSScriptRoot "..\.env"
if (-not (Test-Path $envFile)) {
    Write-Host "Error: .env file not found at $envFile" -ForegroundColor Red
    exit 1
}

$token = (Get-Content $envFile | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""

if (-not $token) {
    Write-Host "Error: ADMIN_TOKEN not found in .env" -ForegroundColor Red
    exit 1
}

# Load or generate test pack
$testPackDir = Join-Path $PSScriptRoot "testpacks"
if (-not (Test-Path $testPackDir)) {
    New-Item -ItemType Directory -Path $testPackDir | Out-Null
}

if ($TestPackPath) {
    $packPath = $TestPackPath
} else {
    $packPath = Join-Path $testPackDir "${TenantId}_confidence_pack.json"
}

if (-not (Test-Path $packPath)) {
    Write-Host "Test pack not found at $packPath. Generating default pack..." -ForegroundColor Yellow
    # Generate default pack (simplified)
    $defaultPack = @{
        should_hit = @("my powerpoint stopped working", "lights flickering", "smoke alarm beeping")
        should_miss = @("toilet blocked", "gas heater broken")
        edge_unclear = @("help", "???")
    } | ConvertTo-Json -Depth 10
    $defaultPack | Out-File -FilePath $packPath -Encoding UTF8
    Write-Host "Created default pack. Please edit $packPath with full test questions." -ForegroundColor Yellow
    exit 1
}

$testPack = Get-Content $packPath | ConvertFrom-Json

# Scale test: duplicate FAQs to 100
if ($ScaleTest) {
    Write-Host "`n=== SCALE TEST MODE ===" -ForegroundColor Cyan
    Write-Host "Creating scale tenant with 100 FAQs..." -ForegroundColor Yellow
    
    $scaleTenantId = "${TenantId}_scale"
    
    # Get current FAQs
    try {
        $currentFaqs = Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$TenantId/faqs/staged" -Method GET -Headers @{"Authorization"="Bearer $token"} -ErrorAction SilentlyContinue
    } catch {
        Write-Host "Could not fetch current FAQs. Using staging endpoint..." -ForegroundColor Yellow
        $currentFaqs = @()
    }
    
    # If we can't get FAQs, skip scale test
    if (-not $currentFaqs -or $currentFaqs.Count -eq 0) {
        Write-Host "Warning: Could not fetch FAQs for scale test. Skipping scale mode." -ForegroundColor Yellow
        $ScaleTest = $false
    } else {
        # Duplicate FAQs to reach ~100
        $targetCount = 100
        $duplicatesNeeded = [math]::Ceiling($targetCount / $currentFaqs.Count)
        $scaledFaqs = @()
        
        for ($i = 0; $i -lt $duplicatesNeeded; $i++) {
            foreach ($faq in $currentFaqs) {
                $newFaq = $faq.PSObject.Copy()
                if ($i -gt 0) {
                    $newFaq.question = "[$i] $($faq.question)"
                }
                $scaledFaqs += $newFaq
                if ($scaledFaqs.Count -ge $targetCount) { break }
            }
            if ($scaledFaqs.Count -ge $targetCount) { break }
        }
        
        Write-Host "Created $($scaledFaqs.Count) FAQs for scale tenant" -ForegroundColor Green
        
        # Upload to scale tenant
        try {
            $body = $scaledFaqs | ConvertTo-Json -Depth 10
            Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$scaleTenantId/faqs/staged" -Method PUT -Headers @{"Authorization"="Bearer $token"; "Content-Type"="application/json"} -Body $body | Out-Null
            Write-Host "Uploaded to scale tenant staging" -ForegroundColor Green
            
            # Promote
            Start-Sleep -Seconds 2
            Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$scaleTenantId/promote" -Method POST -Headers @{"Authorization"="Bearer $token"} | Out-Null
            Write-Host "Promoted scale tenant" -ForegroundColor Green
            Start-Sleep -Seconds 30
            
            $TenantId = $scaleTenantId
        } catch {
            Write-Host "Error setting up scale tenant: $_" -ForegroundColor Red
            Write-Host "Continuing with regular tenant..." -ForegroundColor Yellow
            $ScaleTest = $false
        }
    }
}

# Clear cache
Write-Host "`n=== CLEARING CACHE ===" -ForegroundColor Cyan
python -c "from app.db import get_conn; conn = get_conn(); conn.execute('DELETE FROM retrieval_cache WHERE tenant_id = %s', ('$TenantId',)); conn.commit(); conn.close(); print('Cache cleared')" 2>&1 | Out-Null

# Results storage
$allResults = @()
$runResults = @()

# Run tests N times
for ($run = 1; $run -le $Runs; $run++) {
    Write-Host "`n=== RUN $run of $Runs ===" -ForegroundColor Cyan
    
    $runStart = Get-Date
    $runData = @{
        run_number = $run
        timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        questions = @()
    }
    
    $latencies = @()
    
    # Test should-hit
    foreach ($q in $testPack.should_hit) {
        $qStart = Get-Date
        try {
            $body = @{tenantId=$TenantId; customerMessage=$q} | ConvertTo-Json -Compress
            $r = Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$TenantId/debug-query" -Method POST -Headers @{"Authorization"="Bearer $token"; "Content-Type"="application/json"} -Body $body -ErrorAction Stop
            $latency = ((Get-Date) - $qStart).TotalSeconds
            $latencies += $latency
            
            $runData.questions += @{
                question = $q
                category = "should_hit"
                faq_hit = $r.faq_hit
                debug_branch = $r.debug_branch
                retrieval_score = $r.retrieval_score
                normalized_input = $r.normalized_input
                chosen_faq_id = $r.chosen_faq_id
                chosen_faq_question = $r.chosen_faq_question
                latency_seconds = $latency
                candidates_count = $r.candidates_count
            }
        } catch {
            $latency = ((Get-Date) - $qStart).TotalSeconds
            $latencies += $latency
            $runData.questions += @{
                question = $q
                category = "should_hit"
                faq_hit = $false
                error = $_.Exception.Message
                latency_seconds = $latency
            }
        }
        Start-Sleep -Milliseconds 200
    }
    
    # Test should-miss
    foreach ($q in $testPack.should_miss) {
        $qStart = Get-Date
        try {
            $body = @{tenantId=$TenantId; customerMessage=$q} | ConvertTo-Json -Compress
            $r = Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$TenantId/debug-query" -Method POST -Headers @{"Authorization"="Bearer $token"; "Content-Type"="application/json"} -Body $body -ErrorAction Stop
            $latency = ((Get-Date) - $qStart).TotalSeconds
            $latencies += $latency
            
            $runData.questions += @{
                question = $q
                category = "should_miss"
                faq_hit = $r.faq_hit
                debug_branch = $r.debug_branch
                retrieval_score = $r.retrieval_score
                normalized_input = $r.normalized_input
                chosen_faq_id = $r.chosen_faq_id
                chosen_faq_question = $r.chosen_faq_question
                latency_seconds = $latency
                candidates_count = $r.candidates_count
            }
        } catch {
            $latency = ((Get-Date) - $qStart).TotalSeconds
            $latencies += $latency
            $runData.questions += @{
                question = $q
                category = "should_miss"
                faq_hit = $false
                error = $_.Exception.Message
                latency_seconds = $latency
            }
        }
        Start-Sleep -Milliseconds 200
    }
    
    # Test edge/unclear
    foreach ($q in $testPack.edge_unclear) {
        $qStart = Get-Date
        try {
            $body = @{tenantId=$TenantId; customerMessage=$q} | ConvertTo-Json -Compress
            $r = Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$TenantId/debug-query" -Method POST -Headers @{"Authorization"="Bearer $token"; "Content-Type"="application/json"} -Body $body -ErrorAction Stop
            $latency = ((Get-Date) - $qStart).TotalSeconds
            $latencies += $latency
            
            $runData.questions += @{
                question = $q
                category = "edge_unclear"
                faq_hit = $r.faq_hit
                debug_branch = $r.debug_branch
                retrieval_score = $r.retrieval_score
                normalized_input = $r.normalized_input
                chosen_faq_id = $r.chosen_faq_id
                chosen_faq_question = $r.chosen_faq_question
                latency_seconds = $latency
                candidates_count = $r.candidates_count
            }
        } catch {
            $latency = ((Get-Date) - $qStart).TotalSeconds
            $latencies += $latency
            $runData.questions += @{
                question = $q
                category = "edge_unclear"
                faq_hit = $false
                error = $_.Exception.Message
                latency_seconds = $latency
            }
        }
        Start-Sleep -Milliseconds 200
    }
    
    # Calculate metrics for this run
    $shouldHit = $runData.questions | Where-Object { $_.category -eq "should_hit" }
    $shouldMiss = $runData.questions | Where-Object { $_.category -eq "should_miss" }
    $edge = $runData.questions | Where-Object { $_.category -eq "edge_unclear" }
    
    $hitRate = if ($shouldHit.Count -gt 0) { [math]::Round((($shouldHit | Where-Object { $_.faq_hit }).Count / $shouldHit.Count) * 100, 1) } else { 0 }
    $wrongHitRate = if ($shouldMiss.Count -gt 0) { [math]::Round((($shouldMiss | Where-Object { $_.faq_hit }).Count / $shouldMiss.Count) * 100, 1) } else { 0 }
    $edgeClarifyRate = if ($edge.Count -gt 0) { [math]::Round((($edge | Where-Object { -not $_.faq_hit }).Count / $edge.Count) * 100, 1) } else { 0 }
    
    $sortedLatencies = $latencies | Sort-Object
    $p50 = if ($sortedLatencies.Count -gt 0) { $sortedLatencies[[math]::Floor($sortedLatencies.Count * 0.5)] } else { 0 }
    $p95 = if ($sortedLatencies.Count -gt 0) { $sortedLatencies[[math]::Floor($sortedLatencies.Count * 0.95)] } else { 0 }
    
    $runData.metrics = @{
        hit_rate = $hitRate
        wrong_hit_rate = $wrongHitRate
        edge_clarify_rate = $edgeClarifyRate
        latency_p50 = [math]::Round($p50, 3)
        latency_p95 = [math]::Round($p95, 3)
        total_questions = $runData.questions.Count
    }
    
    $runResults += $runData
    $allResults += $runData
    
    Write-Host "Run $run complete: Hit rate=$hitRate%, Wrong-hit=$wrongHitRate%, Edge clarify=$edgeClarifyRate%, P50=$([math]::Round($p50, 2))s, P95=$([math]::Round($p95, 2))s" -ForegroundColor Green
}

# Aggregate metrics across runs
$hitRates = $runResults | ForEach-Object { $_.metrics.hit_rate }
$wrongHitRates = $runResults | ForEach-Object { $_.metrics.wrong_hit_rate }
$edgeClarifyRates = $runResults | ForEach-Object { $_.metrics.edge_clarify_rate }
$p50s = $runResults | ForEach-Object { $_.metrics.latency_p50 }
$p95s = $runResults | ForEach-Object { $_.metrics.latency_p95 }

$meanHitRate = [math]::Round(($hitRates | Measure-Object -Average).Average, 1)
$minHitRate = ($hitRates | Measure-Object -Minimum).Minimum
$maxHitRate = ($hitRates | Measure-Object -Maximum).Maximum
$hitRateVariance = [math]::Round($maxHitRate - $minHitRate, 1)

$meanWrongHitRate = [math]::Round(($wrongHitRates | Measure-Object -Average).Average, 1)
$maxWrongHitRate = ($wrongHitRates | Measure-Object -Maximum).Maximum

$meanEdgeClarifyRate = [math]::Round(($edgeClarifyRates | Measure-Object -Average).Average, 1)

$meanP50 = [math]::Round(($p50s | Measure-Object -Average).Average, 3)
$meanP95 = [math]::Round(($p95s | Measure-Object -Average).Average, 3)

# Pass/Fail gates
$passHitRate = $meanHitRate -ge 85
$passWrongHitRate = $maxWrongHitRate -eq 0
$passEdgeClarify = $meanEdgeClarifyRate -ge 70
$passRepeatability = $hitRateVariance -le 5
$passLatencyP50 = $meanP50 -le 2.5
$passLatencyP95 = $meanP95 -le 6

$allPass = $passHitRate -and $passWrongHitRate -and $passEdgeClarify -and $passRepeatability -and $passLatencyP50 -and $passLatencyP95

# Print summary
Write-Host "`n" -NoNewline
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  PRODUCTION CONFIDENCE PACK RESULTS" -ForegroundColor Cyan
Write-Host "  Tenant: $TenantId" -ForegroundColor Gray
Write-Host "  Runs: $Runs" -ForegroundColor Gray
Write-Host "═══════════════════════════════════════════════════════════`n" -ForegroundColor Cyan

Write-Host "[REPEATABILITY METRICS]" -ForegroundColor Yellow
Write-Host "  Hit Rate (should-hit):" -ForegroundColor White
Write-Host "    Mean: $meanHitRate% | Min: $minHitRate% | Max: $maxHitRate% | Variance: $hitRateVariance pp" -ForegroundColor $(if ($passHitRate -and $passRepeatability) { "Green" } else { "Red" })
Write-Host "  Wrong-Hit Rate (should-miss):" -ForegroundColor White
Write-Host "    Mean: $meanWrongHitRate% | Max: $maxWrongHitRate%" -ForegroundColor $(if ($passWrongHitRate) { "Green" } else { "Red" })
Write-Host "  Edge Clarify Rate:" -ForegroundColor White
Write-Host "    Mean: $meanEdgeClarifyRate%" -ForegroundColor $(if ($passEdgeClarify) { "Green" } else { "Yellow" })
Write-Host "  Latency:" -ForegroundColor White
Write-Host "    P50: ${meanP50}s | P95: ${meanP95}s" -ForegroundColor $(if ($passLatencyP50 -and $passLatencyP95) { "Green" } else { "Red" })

Write-Host "`n[PASS/FAIL GATES]" -ForegroundColor Yellow
Write-Host "  Hit Rate >= 85%: $(if ($passHitRate) { '✅ PASS' } else { '❌ FAIL' }) ($meanHitRate%)" -ForegroundColor $(if ($passHitRate) { "Green" } else { "Red" })
Write-Host "  Wrong-Hit Rate = 0%: $(if ($passWrongHitRate) { '✅ PASS' } else { '❌ FAIL' }) (max: $maxWrongHitRate%)" -ForegroundColor $(if ($passWrongHitRate) { "Green" } else { "Red" })
Write-Host "  Edge Clarify >= 70%: $(if ($passEdgeClarify) { '✅ PASS' } else { '❌ FAIL' }) ($meanEdgeClarifyRate%)" -ForegroundColor $(if ($passEdgeClarify) { "Green" } else { "Yellow" })
Write-Host "  Repeatability (variance <= 5pp): $(if ($passRepeatability) { '✅ PASS' } else { '❌ FAIL' }) ($hitRateVariance pp)" -ForegroundColor $(if ($passRepeatability) { "Green" } else { "Red" })
Write-Host "  Latency P50 <= 2.5s: $(if ($passLatencyP50) { '✅ PASS' } else { '❌ FAIL' }) (${meanP50}s)" -ForegroundColor $(if ($passLatencyP50) { "Green" } else { "Red" })
Write-Host "  Latency P95 <= 6s: $(if ($passLatencyP95) { '✅ PASS' } else { '❌ FAIL' }) (${meanP95}s)" -ForegroundColor $(if ($passLatencyP95) { "Green" } else { "Red" })

Write-Host "`n[OVERALL]" -ForegroundColor Yellow
Write-Host "  $(if ($allPass) { '✅ ALL GATES PASSED' } else { '❌ SOME GATES FAILED' })" -ForegroundColor $(if ($allPass) { "Green" } else { "Red" })

# Find top failures
if (-not $allPass) {
    Write-Host "`n[TOP FAILURES]" -ForegroundColor Yellow
    
    # Should-hit misses
    $shouldHitMisses = @()
    foreach ($run in $runResults) {
        $misses = $run.questions | Where-Object { $_.category -eq "should_hit" -and -not $_.faq_hit }
        foreach ($m in $misses) {
            $shouldHitMisses += $m
        }
    }
    $topMisses = $shouldHitMisses | Group-Object question | Sort-Object Count -Descending | Select-Object -First 5
    if ($topMisses) {
        Write-Host "  Should-hit misses (most frequent):" -ForegroundColor White
        foreach ($tm in $topMisses) {
            Write-Host "    - $($tm.Name) (missed $($tm.Count)/$Runs runs)" -ForegroundColor Red
        }
    }
    
    # Wrong hits
    $wrongHits = @()
    foreach ($run in $runResults) {
        $hits = $run.questions | Where-Object { $_.category -eq "should_miss" -and $_.faq_hit }
        foreach ($h in $hits) {
            $wrongHits += $h
        }
    }
    $topWrongHits = $wrongHits | Group-Object question | Sort-Object Count -Descending | Select-Object -First 5
    if ($topWrongHits) {
        Write-Host "  Wrong hits (most frequent):" -ForegroundColor White
        foreach ($twh in $topWrongHits) {
            Write-Host "    - $($twh.Name) (hit $($twh.Count)/$Runs runs)" -ForegroundColor Red
        }
    }
}

# Save results
$resultsDir = Join-Path $PSScriptRoot "results"
if (-not (Test-Path $resultsDir)) {
    New-Item -ItemType Directory -Path $resultsDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$resultsFile = Join-Path $resultsDir "confidence_${TenantId}_${timestamp}.json"

$output = @{
    tenant_id = $TenantId
    test_pack = $packPath
    runs = $Runs
    timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    scale_test = $ScaleTest
    summary_metrics = @{
        hit_rate = @{
            mean = $meanHitRate
            min = $minHitRate
            max = $maxHitRate
            variance = $hitRateVariance
        }
        wrong_hit_rate = @{
            mean = $meanWrongHitRate
            max = $maxWrongHitRate
        }
        edge_clarify_rate = @{
            mean = $meanEdgeClarifyRate
        }
        latency = @{
            p50_mean = $meanP50
            p95_mean = $meanP95
        }
    }
    gates = @{
        hit_rate_ge_85 = $passHitRate
        wrong_hit_rate_eq_0 = $passWrongHitRate
        edge_clarify_ge_70 = $passEdgeClarify
        repeatability_variance_le_5 = $passRepeatability
        latency_p50_le_2_5 = $passLatencyP50
        latency_p95_le_6 = $passLatencyP95
        all_passed = $allPass
    }
    runs = $runResults
}

$output | ConvertTo-Json -Depth 10 | Out-File -FilePath $resultsFile -Encoding UTF8
Write-Host "`nResults saved to: $resultsFile" -ForegroundColor Green

exit $(if ($allPass) { 0 } else { 1 })

