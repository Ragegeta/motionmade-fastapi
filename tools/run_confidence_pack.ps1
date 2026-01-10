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
    [string]$TestPackPath = $null,
    
    [Parameter(Mandatory=$false)]
    [switch]$DebugTimings = $false,
    
    [Parameter(Mandatory=$false)]
    [int]$MaxCases = 0  # 0 = no limit
)

$ErrorActionPreference = "Stop"

# Set working directory to repo root
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

# Create results directory and output file path early
$resultsDir = Join-Path $PSScriptRoot "results"
if (-not (Test-Path $resultsDir)) {
    New-Item -ItemType Directory -Path $resultsDir | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outPath = Join-Path $resultsDir "confidence_${TenantId}_${timestamp}.json"

# Write initial stub JSON with status="running"
$initialStub = @{
    tenant_id = $TenantId
    timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    status = "running"
    results = @()
    results_count = 0
} | ConvertTo-Json -Depth 12
$initialStub | Out-File -FilePath $outPath -Encoding UTF8

# Function to write incremental progress
function Write-IncrementalProgress {
    param(
        [array]$Results,
        [string]$FilePath
    )
    
    $currentCount = $Results.Count
    $stub = @{
        tenant_id = $TenantId
        timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        status = "running"
        results = $Results
        results_count = $currentCount
    }
    
    # Calculate basic metrics if we have results
    if ($currentCount -gt 0) {
        $shouldHit = $Results | Where-Object { $_.category -eq "should_hit" }
        $shouldMiss = $Results | Where-Object { $_.category -eq "should_miss" }
        $edge = $Results | Where-Object { $_.category -eq "edge_unclear" }
        
        $hitRate = if ($shouldHit.Count -gt 0) { 
            [math]::Round((($shouldHit | Where-Object { $_.faq_hit }).Count / $shouldHit.Count) * 100, 1) 
        } else { 0 }
        
        $wrongHitRate = if ($shouldMiss.Count -gt 0) { 
            [math]::Round((($shouldMiss | Where-Object { $_.faq_hit }).Count / $shouldMiss.Count) * 100, 1) 
        } else { 0 }
        
        $edgeClarifyRate = if ($edge.Count -gt 0) { 
            [math]::Round((($edge | Where-Object { -not $_.faq_hit }).Count / $edge.Count) * 100, 1) 
        } else { 0 }
        
        $stub.summary_metrics = @{
            hit_rate = $hitRate
            wrong_hit_rate = $wrongHitRate
            edge_clarify_rate = $edgeClarifyRate
            results_count = $currentCount
        }
    }
    
    $stub | ConvertTo-Json -Depth 12 | Out-File -FilePath $FilePath -Encoding UTF8
}

# Function to make HTTP request with comprehensive error handling
function Invoke-QueryWithDiagnostics {
    param(
        [string]$Question,
        [string]$Category,
        [string]$TenantId,
        [string]$AdminBase,
        [string]$PublicBase,
        [string]$Token,
        [string]$AdminTokenForTimings,
        [bool]$DebugTimings
    )
    
    $httpStart = Get-Date
    $requestBody = @{tenantId=$TenantId; customerMessage=$Question} | ConvertTo-Json -Compress
    $requestBodyJson = $requestBody  # Store for diagnostics
    
    # Choose endpoint and headers based on DebugTimings
    if ($DebugTimings) {
        $requestUrl = "$PublicBase/api/v2/generate-quote-reply"
        $requestHeaders = @{
            "Content-Type" = "application/json"
            "X-Debug-Timings" = "1"
            "Authorization" = "Bearer $adminTokenForTimings"
        }
    } else {
        $requestUrl = "$AdminBase/admin/api/tenant/$TenantId/debug-query"
        $requestHeaders = @{
            "Authorization" = "Bearer $token"
            "Content-Type" = "application/json"
        }
    }
    
    # Base result with required fields
    $result = @{
        input = $Question
        request_url = $requestUrl
        request_body_json = $requestBodyJson
        category = $Category
        client_error = $false
    }
    
    try {
        $response = Invoke-WebRequest -Uri $requestUrl -Method POST -Headers $requestHeaders -Body $requestBody -ErrorAction Stop -UseBasicParsing
        $httpLatencyMs = ((Get-Date) - $httpStart).TotalMilliseconds
        
        $statusCode = $response.StatusCode
        $result.status_code = $statusCode
        $result.http_latency_ms = $httpLatencyMs
        
        # Capture raw headers snippet (first ~30 lines)
        $headerLines = @()
        $headerCount = 0
        foreach ($k in $response.Headers.Keys) {
            if ($headerCount -ge 30) { break }
            $headerLines += "$k`: $($response.Headers[$k])"
            $headerCount++
        }
        $result.raw_headers_snippet = ($headerLines -join "`n")
        
        # Capture raw body snippet (first 500 chars)
        $bodyText = $response.Content
        if ($bodyText.Length -gt 500) {
            $result.raw_body_snippet = $bodyText.Substring(0, 500)
        } else {
            $result.raw_body_snippet = $bodyText
        }
        
        # Parse JSON response
        try {
            $r = $response.Content | ConvertFrom-Json
        } catch {
            $r = $null
        }
        
        # Capture all response headers (lowercased keys)
        $hdrs = @{}
        foreach ($k in $response.Headers.Keys) {
            $hdrs[$k.ToLower()] = $response.Headers[$k]
        }
        
        # Extract fields from response body or headers
        $result.faq_hit = if ($r -and $r.faq_hit) { $r.faq_hit } else { ($hdrs["x-faq-hit"] -eq "true") }
        $result.debug_branch = if ($r -and $r.debug_branch) { $r.debug_branch } else { $hdrs["x-debug-branch"] }
        $result.retrieval_score = if ($r -and $r.retrieval_score) { $r.retrieval_score } else { 
            if ($hdrs["x-retrieval-score"]) { [double]$hdrs["x-retrieval-score"] } else { $null }
        }
        $result.normalized_input = if ($r -and $r.normalized_input) { $r.normalized_input } else { $hdrs["x-normalized-input"] }
        $result.chosen_faq_id = if ($r -and $r.chosen_faq_id) { $r.chosen_faq_id } else { $hdrs["x-top-faq-id"] }
        $result.chosen_faq_question = if ($r) { $r.chosen_faq_question } else { $null }
        $result.candidates_count = if ($r -and $r.candidate_count) { $r.candidate_count } else { 
            if ($hdrs["x-candidate-count"]) { [int]$hdrs["x-candidate-count"] } else { 0 }
        }
        $result.retrieval_stage = if ($r -and $r.retrieval_stage) { $r.retrieval_stage } else { $hdrs["x-retrieval-stage"] }
        
        # Determine selector_called (header uses "1"/"0" format, like x-retrieval-used-fts-only)
        $selectorCalled = $false
        if ($hdrs.ContainsKey("x-selector-called")) {
            $selectorCalled = ($hdrs["x-selector-called"] -eq "1")
        } elseif ($hdrs.ContainsKey("x-retrieval-stage")) {
            $selectorCalled = ($hdrs["x-retrieval-stage"] -like "*selector*")
        }
        if (-not $selectorCalled -and $r -and $r.selector_called) {
            # Fallback: check if selector_called is already set in response (for backwards compatibility)
            $selectorCalled = ($r.selector_called -eq $true) -or ($r.selector_called -eq "true") -or ($r.selector_called -eq "1")
        }
        $result.selector_called = $selectorCalled
        $result.headers = $hdrs
        
        # Parse timing headers if DebugTimings is enabled
        if ($DebugTimings) {
            $parseTiming = {
                param($headerName)
                $val = $hdrs[$headerName.ToLower()]
                if ($null -ne $val -and $val -ne "") {
                    $parsed = 0
                    if ([int]::TryParse($val, [ref]$parsed)) {
                        return $parsed
                    }
                }
                return $null
            }
            
            $result.timing_total_ms = & $parseTiming "X-Timing-Total"
            $result.timing_triage_ms = & $parseTiming "X-Timing-Triage"
            $result.timing_normalize_ms = & $parseTiming "X-Timing-Normalize"
            $result.timing_embed_ms = & $parseTiming "X-Timing-Embed"
            $result.timing_retrieval_ms = & $parseTiming "X-Timing-Retrieval"
            $result.timing_rewrite_ms = & $parseTiming "X-Timing-Rewrite"
            $result.timing_llm_ms = & $parseTiming "X-Timing-LLM"
            $result.cache_hit = ($hdrs["x-cache-hit"] -eq "true")
            $result.retrieval_stage_header = $hdrs["x-retrieval-stage"]
            $result.response_size_bytes = $response.RawContentLength
        }
        
    } catch {
        $httpLatencyMs = ((Get-Date) - $httpStart).TotalMilliseconds
        $result.client_error = $true
        $result.exception_type = $_.Exception.GetType().FullName
        $result.exception_message = $_.Exception.Message
        $result.http_latency_ms = $httpLatencyMs
        
        # Try to get HTTP status from exception
        $httpStatusFromException = $null
        if ($_.Exception.Response) {
            try {
                $httpStatusFromException = $_.Exception.Response.StatusCode.value__
                $result.status_code = $httpStatusFromException
                $result.http_status_from_exception = $httpStatusFromException
            } catch {
                $result.status_code = 0
            }
        } else {
            $result.status_code = 0
        }
        
        # Try to capture response snippet if available
        $rawResponseSnippet = $null
        if ($_.Exception.Response) {
            try {
                $stream = $_.Exception.Response.GetResponseStream()
                $reader = New-Object System.IO.StreamReader($stream)
                $rawResponseSnippet = $reader.ReadToEnd()
                if ($rawResponseSnippet.Length -gt 500) {
                    $rawResponseSnippet = $rawResponseSnippet.Substring(0, 500)
                }
                $reader.Close()
                $stream.Close()
            } catch {
                # Response stream not available
            }
        }
        $result.raw_response_snippet = $rawResponseSnippet
        
        # Capture headers if available
        $hdrs = @{}
        if ($_.Exception.Response) {
            try {
                foreach ($k in $_.Exception.Response.Headers.Keys) {
                    $hdrs[$k.ToLower()] = $_.Exception.Response.Headers[$k]
                }
                # Capture raw headers snippet
                $headerLines = @()
                $headerCount = 0
                foreach ($k in $_.Exception.Response.Headers.Keys) {
                    if ($headerCount -ge 30) { break }
                    $headerLines += "$k`: $($_.Exception.Response.Headers[$k])"
                    $headerCount++
                }
                $result.raw_headers_snippet = ($headerLines -join "`n")
            } catch {
                # Headers not available
            }
        }
        $result.headers = $hdrs
        
        # Set defaults for missing fields
        $result.faq_hit = $false
        $result.selector_called = $false
        
        # Timing headers not available on error
        if ($DebugTimings) {
            $result.timing_total_ms = $null
            $result.timing_triage_ms = $null
            $result.timing_normalize_ms = $null
            $result.timing_embed_ms = $null
            $result.timing_retrieval_ms = $null
            $result.timing_rewrite_ms = $null
            $result.timing_llm_ms = $null
            $result.cache_hit = $false
            $result.retrieval_stage_header = $null
            $result.response_size_bytes = 0
        }
    }
    
    return $result
}

# Get admin token (for admin endpoints)
$envFile = Join-Path $RepoRoot ".env"
if (-not (Test-Path $envFile)) {
    Write-Host "Error: .env file not found at $envFile" -ForegroundColor Red
    exit 1
}

$token = (Get-Content $envFile | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""

if (-not $token) {
    Write-Host "Error: ADMIN_TOKEN not found in .env" -ForegroundColor Red
    exit 1
}

# Get ADMIN_TOKEN for DebugTimings (from env var or .env)
$adminTokenForTimings = $env:ADMIN_TOKEN
if (-not $adminTokenForTimings) {
    $adminTokenForTimings = $token  # Fallback to same token from .env
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
    # Generate default pack (simplified)
    $defaultPack = @{
        should_hit = @("my powerpoint stopped working", "lights flickering", "smoke alarm beeping")
        should_miss = @("toilet blocked", "gas heater broken")
        edge_unclear = @("help", "???")
    } | ConvertTo-Json -Depth 10
    $defaultPack | Out-File -FilePath $packPath -Encoding UTF8
    Write-Host "Error: Test pack not found. Created default at $packPath. Please edit with full test questions." -ForegroundColor Red
    exit 1
}

$testPack = Get-Content $packPath | ConvertFrom-Json
$originalTenantId = $TenantId

# Scale test: duplicate FAQs to 100
if ($ScaleTest) {
    
    $scaleTenantId = "${TenantId}_scale"
    
    # Get current FAQs
    try {
        $currentFaqs = Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$TenantId/faqs/staged" -Method GET -Headers @{"Authorization"="Bearer $token"} -ErrorAction SilentlyContinue
    } catch {
        $currentFaqs = @()
    }
    
    # If we can't get FAQs, skip scale test
    if (-not $currentFaqs -or $currentFaqs.Count -eq 0) {
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
        
        # Upload to scale tenant
        try {
            $body = $scaledFaqs | ConvertTo-Json -Depth 10
            Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$scaleTenantId/faqs/staged" -Method PUT -Headers @{"Authorization"="Bearer $token"; "Content-Type"="application/json"} -Body $body | Out-Null
            
            # Promote
            Start-Sleep -Seconds 2
            Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$scaleTenantId/promote" -Method POST -Headers @{"Authorization"="Bearer $token"} | Out-Null
            Start-Sleep -Seconds 30
            
            $TenantId = $scaleTenantId
            # Use the same test pack (copy path for scale tenant lookup)
            $originalPackPath = $packPath
        } catch {
            $ScaleTest = $false
        }
    }
}

# If scale test changed tenant, ensure we use the original test pack
if ($ScaleTest -and $TenantId -ne $originalTenantId) {
    # Use the original tenant's test pack
    $packPath = $originalPackPath
    if (-not (Test-Path $packPath)) {
        Write-Host "Error: Test pack not found at $packPath" -ForegroundColor Red
        exit 1
    }
    $testPack = Get-Content $packPath | ConvertFrom-Json
}

# Clear cache (optional - only affects cache, not tenant data)
# Cache will naturally expire, but clearing ensures fresh results
try {
    python -c "from app.db import get_conn; conn = get_conn(); conn.execute('DELETE FROM retrieval_cache WHERE tenant_id = %s', ('$TenantId',)); conn.commit(); conn.close(); print('Cache cleared')" 2>&1 | Out-Null
} catch {
    # Non-critical, continue
}

# Results storage
$allResults = @()  # Flat list of all cases across all runs
$runResults = @()  # Per-run data structure
$scriptError = $null

# Wrap entire execution in try-catch to ensure error is written to JSON
try {
    # Run tests N times
for ($run = 1; $run -le $Runs; $run++) {
    $runStart = Get-Date
    $runData = @{
        run_number = $run
        timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        questions = @()
    }
    
    $httpLatenciesMs = @()
    $totalCaseLatenciesMs = @()
    $totalSleepMs = 0
    $questionCount = 0
    $totalQuestions = $testPack.should_hit.Count + $testPack.should_miss.Count + $testPack.edge_unclear.Count
    $sleepMsPerRequest = 200
    
    # Apply MaxCases limit if specified
    $shouldHitList = $testPack.should_hit
    $shouldMissList = $testPack.should_miss
    $edgeUnclearList = $testPack.edge_unclear
    
    if ($MaxCases -gt 0) {
        $shouldHitList = $testPack.should_hit | Select-Object -First $MaxCases
        $shouldMissList = $testPack.should_miss | Select-Object -First $MaxCases
        $edgeUnclearList = $testPack.edge_unclear | Select-Object -First $MaxCases
        $totalQuestions = $shouldHitList.Count + $shouldMissList.Count + $edgeUnclearList.Count
    }
    
    # Test should-hit
    foreach ($q in $shouldHitList) {
        $questionCount++
        $caseStart = Get-Date
        
        $questionResult = Invoke-QueryWithDiagnostics `
            -Question $q `
            -Category "should_hit" `
            -TenantId $TenantId `
            -AdminBase $AdminBase `
            -PublicBase $PublicBase `
            -Token $token `
            -AdminTokenForTimings $adminTokenForTimings `
            -DebugTimings $DebugTimings
        
        $questionResult.run_number = $run
        $questionResult.sleep_ms = $sleepMsPerRequest
        $questionResult.latency_seconds = ($questionResult.http_latency_ms / 1000.0)
        
        $httpLatenciesMs += $questionResult.http_latency_ms
        $totalSleepMs += $sleepMsPerRequest
        $caseEnd = Get-Date
        $totalCaseMs = (($caseEnd - $caseStart).TotalMilliseconds)
        $totalCaseLatenciesMs += $totalCaseMs
        $questionResult.total_case_ms = $totalCaseMs
        
        # Add to both runData and allResults immediately
        $runData.questions += $questionResult
        $allResults += $questionResult
        
        # Progress every 10 questions - write incremental JSON
        if ($questionCount % 10 -eq 0) {
            Write-Host "  Progress: $questionCount/$totalQuestions questions" -ForegroundColor Gray
            Write-IncrementalProgress -Results $allResults -FilePath $outPath
        }
        
        Start-Sleep -Milliseconds $sleepMsPerRequest  # Rate limiting - tracked separately
    }
    
    # Test should-miss
    foreach ($q in $shouldMissList) {
        $questionCount++
        $caseStart = Get-Date
        
        $questionResult = Invoke-QueryWithDiagnostics `
            -Question $q `
            -Category "should_miss" `
            -TenantId $TenantId `
            -AdminBase $AdminBase `
            -PublicBase $PublicBase `
            -Token $token `
            -AdminTokenForTimings $adminTokenForTimings `
            -DebugTimings $DebugTimings
        
        $questionResult.run_number = $run
        $questionResult.sleep_ms = $sleepMsPerRequest
        $questionResult.latency_seconds = ($questionResult.http_latency_ms / 1000.0)
        
        $httpLatenciesMs += $questionResult.http_latency_ms
        $totalSleepMs += $sleepMsPerRequest
        $caseEnd = Get-Date
        $totalCaseMs = (($caseEnd - $caseStart).TotalMilliseconds)
        $totalCaseLatenciesMs += $totalCaseMs
        $questionResult.total_case_ms = $totalCaseMs
        
        # Add to both runData and allResults immediately
        $runData.questions += $questionResult
        $allResults += $questionResult
        
        # Progress every 10 questions - write incremental JSON
        if ($questionCount % 10 -eq 0) {
            Write-Host "  Progress: $questionCount/$totalQuestions questions" -ForegroundColor Gray
            Write-IncrementalProgress -Results $allResults -FilePath $outPath
        }
        
        Start-Sleep -Milliseconds $sleepMsPerRequest  # Rate limiting - tracked separately
    }
    
    # Test edge/unclear
    foreach ($q in $edgeUnclearList) {
        $questionCount++
        $caseStart = Get-Date
        
        $questionResult = Invoke-QueryWithDiagnostics `
            -Question $q `
            -Category "edge_unclear" `
            -TenantId $TenantId `
            -AdminBase $AdminBase `
            -PublicBase $PublicBase `
            -Token $token `
            -AdminTokenForTimings $adminTokenForTimings `
            -DebugTimings $DebugTimings
        
        $questionResult.run_number = $run
        $questionResult.sleep_ms = $sleepMsPerRequest
        $questionResult.latency_seconds = ($questionResult.http_latency_ms / 1000.0)
        
        $httpLatenciesMs += $questionResult.http_latency_ms
        $totalSleepMs += $sleepMsPerRequest
        $caseEnd = Get-Date
        $totalCaseMs = (($caseEnd - $caseStart).TotalMilliseconds)
        $totalCaseLatenciesMs += $totalCaseMs
        $questionResult.total_case_ms = $totalCaseMs
        
        # Add to both runData and allResults immediately
        $runData.questions += $questionResult
        $allResults += $questionResult
        
        # Progress every 10 questions - write incremental JSON
        if ($questionCount % 10 -eq 0) {
            Write-Host "  Progress: $questionCount/$totalQuestions questions" -ForegroundColor Gray
            Write-IncrementalProgress -Results $allResults -FilePath $outPath
        }
        
        Start-Sleep -Milliseconds $sleepMsPerRequest  # Rate limiting - tracked separately
    }
    
    # Calculate metrics for this run
    $shouldHit = $runData.questions | Where-Object { $_.category -eq "should_hit" }
    $shouldMiss = $runData.questions | Where-Object { $_.category -eq "should_miss" }
    $edge = $runData.questions | Where-Object { $_.category -eq "edge_unclear" }
    
    $hitRate = if ($shouldHit.Count -gt 0) { [math]::Round((($shouldHit | Where-Object { $_.faq_hit }).Count / $shouldHit.Count) * 100, 1) } else { 0 }
    $wrongHitRate = if ($shouldMiss.Count -gt 0) { [math]::Round((($shouldMiss | Where-Object { $_.faq_hit }).Count / $shouldMiss.Count) * 100, 1) } else { 0 }
    $edgeClarifyRate = if ($edge.Count -gt 0) { [math]::Round((($edge | Where-Object { -not $_.faq_hit }).Count / $edge.Count) * 100, 1) } else { 0 }
    
    # Calculate latency percentiles from HTTP latencies only (excludes sleep time)
    $sortedHttpLatencies = $httpLatenciesMs | Sort-Object
    $httpP50 = if ($sortedHttpLatencies.Count -gt 0) { $sortedHttpLatencies[[math]::Floor($sortedHttpLatencies.Count * 0.5)] } else { 0 }
    $httpP95 = if ($sortedHttpLatencies.Count -gt 0) { $sortedHttpLatencies[[math]::Floor($sortedHttpLatencies.Count * 0.95)] } else { 0 }
    
    # Calculate total case latencies (HTTP + sleep)
    $sortedTotalCaseLatencies = $totalCaseLatenciesMs | Sort-Object
    $totalCaseP50 = if ($sortedTotalCaseLatencies.Count -gt 0) { $sortedTotalCaseLatencies[[math]::Floor($sortedTotalCaseLatencies.Count * 0.5)] } else { 0 }
    $totalCaseP95 = if ($sortedTotalCaseLatencies.Count -gt 0) { $sortedTotalCaseLatencies[[math]::Floor($sortedTotalCaseLatencies.Count * 0.95)] } else { 0 }
    
    # Selector called rate (computed from results, not counter)
    $runSelectorCalledCount = ($runData.questions | Where-Object { 
        $val = $_.selector_called
        $null -ne $val -and ($val -is [bool] -and $val -eq $true)
    }).Count
    $selectorCalledRate = if ($runData.questions.Count -gt 0) { [math]::Round(($runSelectorCalledCount / $runData.questions.Count) * 100, 1) } else { 0 }
    
    $runData.metrics = @{
        hit_rate = $hitRate
        wrong_hit_rate = $wrongHitRate
        edge_clarify_rate = $edgeClarifyRate
        http_latency_p50_ms = [math]::Round($httpP50, 2)
        http_latency_p95_ms = [math]::Round($httpP95, 2)
        total_case_p50_ms = [math]::Round($totalCaseP50, 2)
        total_case_p95_ms = [math]::Round($totalCaseP95, 2)
        sleep_ms_total = $totalSleepMs
        selector_called_rate = $selectorCalledRate
        total_questions = $runData.questions.Count
    }
    
    # Results already added to allResults during the loop
    $runResults += $runData
}

} catch {
    $scriptError = $_.Exception.Message
    Write-Host "Error during execution: $scriptError" -ForegroundColor Red
    
    # Write error to JSON
    $errorOutput = @{
        tenant_id = $TenantId
        timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        status = "error"
        error = $scriptError
        results = $allResults
        results_count = $allResults.Count
    }
    $errorOutput | ConvertTo-Json -Depth 12 | Out-File -FilePath $outPath -Encoding UTF8
    exit 1
}

# Sanity check: ensure we have results
if ($allResults.Count -eq 0) {
    Write-Host "Error: No results collected. Exiting." -ForegroundColor Red
    
    # Write error to JSON without misleading summary
    $errorOutput = @{
        tenant_id = $TenantId
        timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        status = "error"
        error = "No results collected - all requests may have failed"
        results = @()
        results_count = 0
    }
    $errorOutput | ConvertTo-Json -Depth 12 | Out-File -FilePath $outPath -Encoding UTF8
    exit 1
}

# Compute summary metrics from flat results array (wrapped in try/catch for safety)
$summaryError = $null
try {
    $shouldHitResults = $allResults | Where-Object { $_.category -eq "should_hit" }
    $shouldMissResults = $allResults | Where-Object { $_.category -eq "should_miss" }
    $edgeResults = $allResults | Where-Object { $_.category -eq "edge_unclear" }

    # Hit rate (should-hit) - calculate per run for variance
    $hitRatesByRun = @{}
    foreach ($r in $shouldHitResults) {
        $runNum = $r.run_number
        if (-not $hitRatesByRun.ContainsKey($runNum)) {
            $hitRatesByRun[$runNum] = @{ total = 0; hits = 0 }
        }
        $hitRatesByRun[$runNum].total++
        if ($r.faq_hit) { $hitRatesByRun[$runNum].hits++ }
    }
    $runHitRates = $hitRatesByRun.Keys | ForEach-Object {
        if ($hitRatesByRun[$_].total -gt 0) {
            [math]::Round(($hitRatesByRun[$_].hits / $hitRatesByRun[$_].total) * 100, 1)
        } else { 0 }
    }
    $meanHitRate = if ($runHitRates.Count -gt 0) { [math]::Round(($runHitRates | Measure-Object -Average).Average, 1) } else { 0 }
    $minHitRate = if ($runHitRates.Count -gt 0) { ($runHitRates | Measure-Object -Minimum).Minimum } else { 0 }
    $maxHitRate = if ($runHitRates.Count -gt 0) { ($runHitRates | Measure-Object -Maximum).Maximum } else { 0 }
    $hitRateVariance = [math]::Round($maxHitRate - $minHitRate, 1)

    # Wrong-hit rate (should-miss)
    $wrongHitCount = ($shouldMissResults | Where-Object { $_.faq_hit }).Count
    $meanWrongHitRate = if ($shouldMissResults.Count -gt 0) { [math]::Round(($wrongHitCount / $shouldMissResults.Count) * 100, 1) } else { 0 }
    # Max wrong-hit rate across runs
    $wrongHitRatesByRun = @{}
    foreach ($r in $shouldMissResults) {
        $runNum = $r.run_number
        if (-not $wrongHitRatesByRun.ContainsKey($runNum)) {
            $wrongHitRatesByRun[$runNum] = @{ total = 0; hits = 0 }
        }
        $wrongHitRatesByRun[$runNum].total++
        if ($r.faq_hit) { $wrongHitRatesByRun[$runNum].hits++ }
    }
    $runWrongHitRates = $wrongHitRatesByRun.Keys | ForEach-Object {
        if ($wrongHitRatesByRun[$_].total -gt 0) {
            [math]::Round(($wrongHitRatesByRun[$_].hits / $wrongHitRatesByRun[$_].total) * 100, 1)
        } else { 0 }
    }
    $maxWrongHitRate = if ($runWrongHitRates.Count -gt 0) { ($runWrongHitRates | Measure-Object -Maximum).Maximum } else { 0 }

    # Edge clarify rate - only count if status_code==200 and response explicitly indicates clarify
    # Check for clarify indicators in response body or headers
    $edgeClarifyCount = ($edgeResults | Where-Object { 
        $statusOk = ($_.status_code -eq 200)
        $notFaqHit = (-not $_.faq_hit)
        # Check if response body contains clarify indicators
        $bodyIndicatesClarify = $false
        if ($_.raw_body_snippet) {
            $bodyLower = $_.raw_body_snippet.ToLower()
            $bodyIndicatesClarify = ($bodyLower -match "rephrase|more detail|clarify|please provide|can you provide")
        }
        # Check debug branch for clarify
        $branchIndicatesClarify = ($_.debug_branch -like "*clarify*")
        return ($statusOk -and $notFaqHit -and ($bodyIndicatesClarify -or $branchIndicatesClarify))
    }).Count
    $meanEdgeClarifyRate = if ($edgeResults.Count -gt 0) { [math]::Round(($edgeClarifyCount / $edgeResults.Count) * 100, 1) } else { 0 }
    
    # Count non-200 responses
    $non200Count = ($allResults | Where-Object { 
        $sc = $_.status_code
        $null -ne $sc -and $sc -ne 0 -and $sc -ne 200
    }).Count
    
    # Count client errors (exceptions)
    $clientErrorCount = ($allResults | Where-Object { $_.client_error -eq $true }).Count

    # HTTP latency (from all results) - filter to numeric only, default to 0 if missing
    $httpLatenciesMs = $allResults | ForEach-Object {
        $val = $_.http_latency_ms
        if ($null -ne $val -and ($val -is [int] -or $val -is [double] -or $val -is [decimal])) {
            [double]$val
        } else { 0 }
    } | Where-Object { $_ -gt 0 }
    $sortedHttpLatencies = $httpLatenciesMs | Sort-Object
    $httpP50 = if ($sortedHttpLatencies.Count -gt 0) { $sortedHttpLatencies[[math]::Floor($sortedHttpLatencies.Count * 0.5)] } else { 0 }
    $httpP95 = if ($sortedHttpLatencies.Count -gt 0) { $sortedHttpLatencies[[math]::Floor($sortedHttpLatencies.Count * 0.95)] } else { 0 }
    $meanHttpP50 = [math]::Round($httpP50, 2)
    $meanHttpP95 = [math]::Round($httpP95, 2)

    # Total case latency - filter to numeric only, default to 0 if missing
    $totalCaseLatenciesMs = $allResults | ForEach-Object {
        $val = $_.total_case_ms
        if ($null -ne $val -and ($val -is [int] -or $val -is [double] -or $val -is [decimal])) {
            [double]$val
        } else { 0 }
    } | Where-Object { $_ -gt 0 }
    $sortedTotalCaseLatencies = $totalCaseLatenciesMs | Sort-Object
    $totalCaseP50 = if ($sortedTotalCaseLatencies.Count -gt 0) { $sortedTotalCaseLatencies[[math]::Floor($sortedTotalCaseLatencies.Count * 0.5)] } else { 0 }
    $totalCaseP95 = if ($sortedTotalCaseLatencies.Count -gt 0) { $sortedTotalCaseLatencies[[math]::Floor($sortedTotalCaseLatencies.Count * 0.95)] } else { 0 }
    $meanTotalCaseP50 = [math]::Round($totalCaseP50, 2)
    $meanTotalCaseP95 = [math]::Round($totalCaseP95, 2)

    # Sleep total - filter to numeric only, default to 0 if missing
    $sleepValues = $allResults | ForEach-Object {
        $val = $_.sleep_ms
        if ($null -ne $val -and ($val -is [int] -or $val -is [double] -or $val -is [decimal])) {
            [double]$val
        } else { 0 }
    }
    $totalSleepMs = if ($sleepValues.Count -gt 0) { ($sleepValues | Measure-Object -Sum).Sum } else { 0 }

    # Selector called rate - compute from flat results array (ensure boolean, not counter)
    $selectorCalledCount = ($allResults | Where-Object { 
        $val = $_.selector_called
        $null -ne $val -and ($val -is [bool] -and $val -eq $true)
    }).Count
    $meanSelectorCalledRate = if ($allResults.Count -gt 0) { 
        [math]::Round(($selectorCalledCount / $allResults.Count) * 100, 1) 
    } else { 0 }

    # Pass/Fail gates (using HTTP latency only)
    $passHitRate = $meanHitRate -ge 85
    $passWrongHitRate = $maxWrongHitRate -eq 0
    $passEdgeClarify = $meanEdgeClarifyRate -ge 70
    $passRepeatability = $hitRateVariance -le 5
    $passLatencyP50 = $meanHttpP50 -le 2500  # 2.5s = 2500ms
    $passLatencyP95 = $meanHttpP95 -le 6000   # 6s = 6000ms

    $allPass = $passHitRate -and $passWrongHitRate -and $passEdgeClarify -and $passRepeatability -and $passLatencyP50 -and $passLatencyP95
} catch {
    $summaryError = $_.Exception.Message
    Write-Host "Warning: Summary computation failed: $summaryError" -ForegroundColor Yellow
    
    # Set defaults on error
    $meanHitRate = 0
    $minHitRate = 0
    $maxHitRate = 0
    $hitRateVariance = 0
    $meanWrongHitRate = 0
    $maxWrongHitRate = 0
    $meanEdgeClarifyRate = 0
    $meanHttpP50 = 0
    $meanHttpP95 = 0
    $meanTotalCaseP50 = 0
    $meanTotalCaseP95 = 0
    $totalSleepMs = 0
    $meanSelectorCalledRate = 0
    $passHitRate = $false
    $passWrongHitRate = $false
    $passEdgeClarify = $false
    $passRepeatability = $false
    $passLatencyP50 = $false
    $passLatencyP95 = $false
    $allPass = $false
}

# Print final summary (quiet mode - only summary)
Write-Host "`n═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  CONFIDENCE PACK RESULTS" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "Hit Rate: $meanHitRate% (min: $minHitRate%, max: $maxHitRate%, variance: $hitRateVariance pp)" -ForegroundColor $(if ($passHitRate -and $passRepeatability) { "Green" } else { "Red" })
Write-Host "Wrong-Hit: $meanWrongHitRate% (max: $maxWrongHitRate%)" -ForegroundColor $(if ($passWrongHitRate) { "Green" } else { "Red" })
Write-Host "Edge Clarify: $meanEdgeClarifyRate%" -ForegroundColor $(if ($passEdgeClarify) { "Green" } else { "Yellow" })
Write-Host "Non-200 Responses: $non200Count" -ForegroundColor $(if ($non200Count -eq 0) { "Green" } else { "Yellow" })
Write-Host "Client Errors: $clientErrorCount" -ForegroundColor $(if ($clientErrorCount -eq 0) { "Green" } else { "Red" })
Write-Host "HTTP Latency (gate metric): p50=$([math]::Round($meanHttpP50/1000, 2))s, p95=$([math]::Round($meanHttpP95/1000, 2))s" -ForegroundColor $(if ($passLatencyP50 -and $passLatencyP95) { "Green" } else { "Red" })
Write-Host "Total Case Latency: p50=$([math]::Round($meanTotalCaseP50/1000, 2))s, p95=$([math]::Round($meanTotalCaseP95/1000, 2))s" -ForegroundColor Gray
Write-Host "Sleep Total: $([math]::Round($totalSleepMs/1000, 1))s" -ForegroundColor Gray
Write-Host "Selector Called Rate: $meanSelectorCalledRate%" -ForegroundColor Gray
Write-Host "Overall: $(if ($allPass) { '✅ PASS' } else { '❌ FAIL' })" -ForegroundColor $(if ($allPass) { "Green" } else { "Red" })

# Sanity check: selector_called_cases cannot exceed total cases
$selectorCalledCases = ($allResults | Where-Object { 
    $val = $_.selector_called
    $null -ne $val -and ($val -is [bool] -and $val -eq $true)
}).Count
$totalCases = $allResults.Count

if ($selectorCalledCases -gt $totalCases) {
    Write-Host "ERROR: selector_called_cases ($selectorCalledCases) exceeds total cases ($totalCases)" -ForegroundColor Red
    
    # Write error to JSON
    $errorOutput = @{
        tenant_id = $TenantId
        timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        status = "error"
        error = "selector_called_cases ($selectorCalledCases) exceeds total cases ($totalCases)"
        results = $allResults
        results_count = $allResults.Count
    }
    $errorOutput | ConvertTo-Json -Depth 12 | Out-File -FilePath $outPath -Encoding UTF8
    exit 1
}

Write-Host "selector_called_cases=$selectorCalledCases/$totalCases" -ForegroundColor Gray

# Print timing summary if DebugTimings is enabled
if ($DebugTimings) {
    Write-Host "`n[TIMING BREAKDOWN]" -ForegroundColor Cyan
    $timingResults = $allResults | Where-Object { $null -ne $_.timing_total_ms }
    
    if ($timingResults.Count -gt 0) {
        # Calculate averages using only non-null numeric values
        $triageValues = $timingResults | Where-Object { $null -ne $_.timing_triage_ms -and ($_.timing_triage_ms -is [int] -or $_.timing_triage_ms -is [double]) } | ForEach-Object { $_.timing_triage_ms }
        $avgTriage = if ($triageValues.Count -gt 0) { [math]::Round(($triageValues | Measure-Object -Average).Average, 1) } else { $null }
        
        $normalizeValues = $timingResults | Where-Object { $null -ne $_.timing_normalize_ms -and ($_.timing_normalize_ms -is [int] -or $_.timing_normalize_ms -is [double]) } | ForEach-Object { $_.timing_normalize_ms }
        $avgNormalize = if ($normalizeValues.Count -gt 0) { [math]::Round(($normalizeValues | Measure-Object -Average).Average, 1) } else { $null }
        
        $embedValues = $timingResults | Where-Object { $null -ne $_.timing_embed_ms -and ($_.timing_embed_ms -is [int] -or $_.timing_embed_ms -is [double]) } | ForEach-Object { $_.timing_embed_ms }
        $avgEmbed = if ($embedValues.Count -gt 0) { [math]::Round(($embedValues | Measure-Object -Average).Average, 1) } else { $null }
        $p95Embed = if ($embedValues.Count -gt 0) { 
            $sorted = $embedValues | Sort-Object
            $sorted[[math]::Floor($sorted.Count * 0.95)]
        } else { $null }
        
        $retrievalValues = $timingResults | Where-Object { $null -ne $_.timing_retrieval_ms -and ($_.timing_retrieval_ms -is [int] -or $_.timing_retrieval_ms -is [double]) } | ForEach-Object { $_.timing_retrieval_ms }
        $avgRetrieval = if ($retrievalValues.Count -gt 0) { [math]::Round(($retrievalValues | Measure-Object -Average).Average, 1) } else { $null }
        $p95Retrieval = if ($retrievalValues.Count -gt 0) { 
            $sorted = $retrievalValues | Sort-Object
            $sorted[[math]::Floor($sorted.Count * 0.95)]
        } else { $null }
        
        $rewriteValues = $timingResults | Where-Object { $null -ne $_.timing_rewrite_ms -and ($_.timing_rewrite_ms -is [int] -or $_.timing_rewrite_ms -is [double]) } | ForEach-Object { $_.timing_rewrite_ms }
        $avgRewrite = if ($rewriteValues.Count -gt 0) { [math]::Round(($rewriteValues | Measure-Object -Average).Average, 1) } else { $null }
        
        $llmValues = $timingResults | Where-Object { $null -ne $_.timing_llm_ms -and ($_.timing_llm_ms -is [int] -or $_.timing_llm_ms -is [double]) } | ForEach-Object { $_.timing_llm_ms }
        $avgLLM = if ($llmValues.Count -gt 0) { [math]::Round(($llmValues | Measure-Object -Average).Average, 1) } else { $null }
        $p95LLM = if ($llmValues.Count -gt 0) { 
            $sorted = $llmValues | Sort-Object
            $sorted[[math]::Floor($sorted.Count * 0.95)]
        } else { $null }
        
        $totalValues = $timingResults | Where-Object { $null -ne $_.timing_total_ms -and ($_.timing_total_ms -is [int] -or $_.timing_total_ms -is [double]) } | ForEach-Object { $_.timing_total_ms }
        $avgTotal = if ($totalValues.Count -gt 0) { [math]::Round(($totalValues | Measure-Object -Average).Average, 1) } else { $null }
        
        $cacheHitCount = ($timingResults | Where-Object { $_.cache_hit -eq $true }).Count
        $cacheHitRate = [math]::Round(($cacheHitCount / $timingResults.Count) * 100, 1)
        
        # Print only if we have data
        if ($null -ne $avgTriage) { Write-Host "  Triage: ${avgTriage}ms avg" -ForegroundColor Gray }
        if ($null -ne $avgNormalize) { Write-Host "  Normalize: ${avgNormalize}ms avg" -ForegroundColor Gray }
        if ($null -ne $avgEmbed) { Write-Host "  Embed: ${avgEmbed}ms avg$(if ($null -ne $p95Embed) { ", ${p95Embed}ms p95" })" -ForegroundColor Gray }
        if ($null -ne $avgRetrieval) { Write-Host "  Retrieval: ${avgRetrieval}ms avg$(if ($null -ne $p95Retrieval) { ", ${p95Retrieval}ms p95" })" -ForegroundColor Gray }
        if ($null -ne $avgRewrite) { Write-Host "  Rewrite: ${avgRewrite}ms avg" -ForegroundColor Gray }
        if ($null -ne $avgLLM) { Write-Host "  LLM: ${avgLLM}ms avg$(if ($null -ne $p95LLM) { ", ${p95LLM}ms p95" })" -ForegroundColor Gray }
        if ($null -ne $avgTotal) { Write-Host "  Total: ${avgTotal}ms avg" -ForegroundColor Gray }
        Write-Host "  Cache Hit Rate: ${cacheHitRate}%" -ForegroundColor Gray
        
        # Check if all timing values are null
        if ($null -eq $avgTriage -and $null -eq $avgNormalize -and $null -eq $avgEmbed -and $null -eq $avgRetrieval -and $null -eq $avgRewrite -and $null -eq $avgLLM -and $null -eq $avgTotal) {
            Write-Host "  Timing headers missing (DEBUG likely off)" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Timing headers missing (DEBUG likely off)" -ForegroundColor Yellow
    }
    
    # Debug print: timing headers present cases
    $timingHeadersPresent = ($allResults | Where-Object { $null -ne $_.timing_total_ms }).Count
    Write-Host "  timing_headers_present_cases=$timingHeadersPresent/$($allResults.Count)" -ForegroundColor Gray
}

# Detailed analysis only in JSON, not stdout

# Write final results
$output = @{
    tenant_id = $TenantId
    timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
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
        non_200_count = $non200Count
        client_error_count = $clientErrorCount
        http_latency = @{
            p50_mean_ms = $meanHttpP50
            p95_mean_ms = $meanHttpP95
        }
        total_case_latency = @{
            p50_mean_ms = $meanTotalCaseP50
            p95_mean_ms = $meanTotalCaseP95
        }
        sleep_ms_total = $totalSleepMs
        selector_called_rate = @{
            mean = $meanSelectorCalledRate
        }
    }
    gates = @{
        hit_rate_ge_85 = $passHitRate
        wrong_hit_rate_eq_0 = $passWrongHitRate
        edge_clarify_ge_70 = $passEdgeClarify
        repeatability_variance_le_5 = $passRepeatability
        http_latency_p50_le_2500ms = $passLatencyP50
        http_latency_p95_le_6000ms = $passLatencyP95
        all_passed = $allPass
    }
    results = $allResults
    runs = $runResults
    status = "completed"
}
if ($summaryError) {
    $output.summary_error = $summaryError
}

$output | ConvertTo-Json -Depth 12 | Out-File -FilePath $outPath -Encoding UTF8
Write-Host "JSON: $outPath" -ForegroundColor Gray

exit $(if ($allPass) { 0 } else { 1 })

