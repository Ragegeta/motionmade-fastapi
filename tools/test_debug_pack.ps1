<#
.SYNOPSIS
    Test pack for debug-query endpoint - generates diverse messages and analyzes results.

.DESCRIPTION
    Generates ~50 diverse test messages (or loads from file) and tests them against the debug-query endpoint.
    Produces detailed scoring report including hit rates, branch breakdown, and worst cases.

.PARAMETER TenantId
    Tenant ID to test (default: sparkys_electrical)

.PARAMETER RenderUrl
    Base URL for API (default: https://motionmade-fastapi.onrender.com)

.PARAMETER TokenPath
    Path to .env file containing ADMIN_TOKEN (default: C:\MM\motionmade-fastapi\.env)

.PARAMETER Count
    Number of messages to generate if MessagesPath not provided (default: 50)

.PARAMETER MessagesPath
    Optional path to JSON/text file with messages to test (one per line or JSON array)

.EXAMPLE
    .\tools\test_debug_pack.ps1 -TenantId sparkys_electrical

.EXAMPLE
    .\tools\test_debug_pack.ps1 -TenantId sparkys_electrical -Count 100

.EXAMPLE
    .\tools\test_debug_pack.ps1 -TenantId sparkys_electrical -MessagesPath messages.json
#>

param(
    [string]$TenantId = "sparkys_electrical",
    [string]$RenderUrl = "https://motionmade-fastapi.onrender.com",
    [string]$TokenPath = "C:\MM\motionmade-fastapi\.env",
    [int]$Count = 50,
    [string]$MessagesPath = ""
)

# Load ADMIN_TOKEN
if (-not (Test-Path $TokenPath)) {
    Write-Host "Error: Token file not found at $TokenPath" -ForegroundColor Red
    exit 1
}

$token = (Get-Content $TokenPath | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
if (-not $token) {
    Write-Host "Error: ADMIN_TOKEN not found in $TokenPath" -ForegroundColor Red
    exit 1
}

# Load or generate messages
$messages = @()

if ($MessagesPath -and (Test-Path $MessagesPath)) {
    Write-Host "Loading messages from $MessagesPath..." -ForegroundColor Cyan
    $content = Get-Content $MessagesPath -Raw
    try {
        $json = $content | ConvertFrom-Json
        if ($json -is [array]) {
            $messages = $json
        } elseif ($json.messages) {
            $messages = $json.messages
        } else {
            $messages = $json
        }
    } catch {
        # Try as line-delimited text
        $messages = Get-Content $MessagesPath | Where-Object { $_.Trim() -ne "" }
    }
} else {
    Write-Host "Generating $Count diverse test messages..." -ForegroundColor Cyan
    
    # Pricing queries (clean + messy)
    $messages += @(
        "how much do you charge",
        "ur prices pls",
        "wat do u charge",
        "what's your call out fee",
        "how much is your hourly rate",
        "pricing",
        "cost",
        "quote please",
        "how much for a new powerpoint",
        "ur rates"
    )
    
    # Services queries
    $messages += @(
        "what services do you offer",
        "do you do powerpoints",
        "can u install ceiling fans",
        "do you do lighting",
        "wat do u do",
        "services",
        "can you do switchboards",
        "do u do smoke alarms"
    )
    
    # Service area queries
    $messages += @(
        "what areas do you service",
        "wat areas do u cover",
        "do you come to brisbane",
        "do u service logan",
        "service area",
        "where do you service"
    )
    
    # Booking/availability queries
    $messages += @(
        "how do i book",
        "can u come today",
        "can you come 2day",
        "availability",
        "when can you come",
        "can you come this arvo",
        "booking"
    )
    
    # Emergency queries
    $messages += @(
        "i have no power",
        "emergency electrician",
        "urgent",
        "no power",
        "power out"
    )
    
    # Licensing/insurance queries
    $messages += @(
        "are you licensed",
        "r u insured",
        "licensed",
        "qualified",
        "insurance"
    )
    
    # Messy/typo-heavy (at least 10)
    $messages += @(
        "g'day mate wat do u charge 4 a new powerpoint",
        "hey quick one - how much",
        "ur prices pls need quote",
        "can u come 2day? urgent",
        "r u licensed? wat areas",
        "do u do ceiling fans? how much",
        "wat do u charge 4 emergency",
        "can u come this arvo? no power",
        "ur rates pls",
        "hey wat areas do u cover",
        "g'day can u come today",
        "quick q - r u insured"
    )
    
    # Fluff/small talk
    $messages += @(
        "hi",
        "hello",
        "hey",
        "g'day",
        "thanks"
    )
    
    # Short fragments
    $messages += @(
        "pricing",
        "services",
        "area",
        "booking",
        "emergency"
    )
    
    # Multi-question
    $messages += @(
        "how much do you charge and what areas do you cover",
        "are you licensed and do you do powerpoints",
        "can you come today and how much is it"
    )
    
    # Should miss (wrong services) - 8-12
    $messages += @(
        "do you do plumbing",
        "can you paint my house",
        "do you do roofing",
        "can you fix my car",
        "do you do landscaping",
        "can you install air conditioning",
        "do you do carpentry",
        "can you do tiling",
        "do you do painting",
        "can you do plastering",
        "do you do concrete work",
        "can you do fencing"
    )
    
    # Ensure should-miss messages are prioritized and kept
    $shouldMissKeywords = @("plumbing", "paint", "roofing", "car", "landscaping", "air conditioning", "carpentry", "tiling", "plastering", "concrete", "fencing")
    $shouldMissMessages = $messages | Where-Object { 
        $msg = $_.ToLower()
        $found = $false
        foreach ($keyword in $shouldMissKeywords) {
            if ($msg -match $keyword) {
                $found = $true
                break
            }
        }
        $found
    }
    $otherMessages = $messages | Where-Object { 
        $msg = $_.ToLower()
        $found = $false
        foreach ($keyword in $shouldMissKeywords) {
            if ($msg -match $keyword) {
                $found = $true
                break
            }
        }
        -not $found
    }
    
    # Rebuild: should-miss first (keep all), then others (trim if needed)
    $messages = @($shouldMissMessages) + @($otherMessages)
    
    # Trim to Count if needed (but keep all should-miss)
    if ($messages.Count -gt $Count) {
        $keepShouldMiss = $shouldMissMessages.Count
        $keepOthers = [Math]::Max(0, $Count - $keepShouldMiss)
        $messages = @($shouldMissMessages) + @($otherMessages[0..($keepOthers-1)])
    } elseif ($messages.Count -lt $Count) {
        # Pad with variations from other messages
        $baseMessages = $otherMessages.Clone()
        while ($messages.Count -lt $Count -and $baseMessages.Count -gt 0) {
            $randomMsg = $baseMessages | Get-Random
            $messages += $randomMsg
            $baseMessages = $baseMessages | Where-Object { $_ -ne $randomMsg }
        }
    }
}

Write-Host "Testing $($messages.Count) messages..." -ForegroundColor Cyan
Write-Host ""

# Test each message
$results = @()
$shouldMiss = @("plumbing", "paint", "roofing", "car", "landscaping", "air conditioning", "carpentry", "tiling", "plastering", "concrete", "fencing")
$shouldMissMessages = $messages | Where-Object { 
    $msg = $_.ToLower()
    $shouldMiss | Where-Object { $msg -match $_ }
}

$i = 0
foreach ($msg in $messages) {
    $i++
    Write-Progress -Activity "Testing messages" -Status "Message $i of $($messages.Count): $($msg.Substring(0, [Math]::Min(40, $msg.Length)))" -PercentComplete (($i / $messages.Count) * 100)
    
    $body = @{
        customerMessage = $msg
    } | ConvertTo-Json -Compress
    
    $result = @{
        message = $msg
        timestamp = (Get-Date).ToUniversalTime().ToString("o")
        faq_hit = $false
        debug_branch = "unknown"
        retrieval_score = $null
        retrieval_stage = $null
        normalized_input = $null
        replyText = $null
        rerank_triggered = $false
        rerank_gate = $null
        triage_result = $null
        top_faq_id = $null
        error = $null
    }
    
    try {
        $response = Invoke-RestMethod -Uri "$RenderUrl/admin/api/tenant/$TenantId/debug-query" `
            -Method POST `
            -Headers @{
                "Authorization" = "Bearer $token"
                "Content-Type" = "application/json"
            } `
            -Body $body `
            -TimeoutSec 30
        
        $result.faq_hit = $response.faq_hit
        $result.debug_branch = $response.debug_branch
        $result.retrieval_score = if ($response.retrieval_score) { [double]$response.retrieval_score } else { $null }
        $result.retrieval_stage = $response.retrieval_stage
        $result.normalized_input = $response.normalized_input
        $result.replyText = $response.replyText
        $result.rerank_triggered = $response.rerank_triggered
        $result.rerank_gate = $response.rerank_gate
        $result.triage_result = $response.triage_result
        $result.top_faq_id = $response.top_faq_id
        
    } catch {
        $result.error = $_.Exception.Message
        if ($_.Exception.Response) {
            $result.http_status = $_.Exception.Response.StatusCode.value__
        }
    }
    
    $results += $result
}

Write-Progress -Activity "Testing messages" -Completed

# Calculate statistics
$total = $results.Count
$hits = ($results | Where-Object { $_.faq_hit }).Count
$misses = $total - $hits
$hitRate = if ($total -gt 0) { [math]::Round(($hits / $total) * 100, 1) } else { 0 }

# Branch breakdown
$branchGroups = $results | Group-Object -Property { if ($_.debug_branch) { $_.debug_branch } else { "(empty)" } }
$branchCounts = $branchGroups | ForEach-Object {
    @{
        branch = $_.Name
        count = $_.Count
        percentage = [math]::Round(($_.Count / $total) * 100, 1)
    }
} | Sort-Object -Property count -Descending

# Should miss analysis
$shouldMissResults = $results | Where-Object { 
    $msg = $_.message.ToLower()
    $found = $false
    foreach ($keyword in $shouldMiss) {
        if ($msg -match $keyword) {
            $found = $true
            break
        }
    }
    $found
}
$shouldMissTotal = $shouldMissResults.Count
$shouldMissHits = ($shouldMissResults | Where-Object { $_.faq_hit }).Count
$wrongHitRate = if ($shouldMissTotal -gt 0) { [math]::Round(($shouldMissHits / $shouldMissTotal) * 100, 1) } else { 0 }

# Top 10 lowest scores among hits
$lowestScores = $results | 
    Where-Object { $_.faq_hit -and $_.retrieval_score -ne $null } | 
    Sort-Object -Property retrieval_score | 
    Select-Object -First 10 | ForEach-Object {
        @{
            message = $_.message
            retrieval_score = $_.retrieval_score
            debug_branch = $_.debug_branch
            normalized_input = $_.normalized_input
        }
    }

# Save results
$resultsDir = "tools\results"
if (-not (Test-Path $resultsDir)) {
    New-Item -ItemType Directory -Path $resultsDir -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$resultsFile = "$resultsDir\debug_pack_${TenantId}_${timestamp}.json"

$output = @{
    metadata = @{
        tenant_id = $TenantId
        render_url = $RenderUrl
        timestamp = (Get-Date).ToUniversalTime().ToString("o")
        total_messages = $total
        messages_source = if ($MessagesPath) { "file: $MessagesPath" } else { "generated" }
    }
    summary = @{
        total = $total
        hits = $hits
        misses = $misses
        hit_rate_percent = $hitRate
        branch_breakdown = $branchCounts
        should_miss_analysis = @{
            total_should_miss = $shouldMissTotal
            wrong_hits = $shouldMissHits
            wrong_hit_rate_percent = $wrongHitRate
        }
        lowest_scores_among_hits = $lowestScores
    }
    results = $results
}

$output | ConvertTo-Json -Depth 10 | Set-Content $resultsFile -Encoding UTF8

# Categorize misses by type
function Get-MessageCategory {
    param([string]$message)
    $msg = $message.ToLower()
    if ($msg -match "price|cost|charge|quote|rate|fee|how much") { return "pricing" }
    if ($msg -match "book|avail|come|when|today|tomorrow|arvo|2day") { return "booking" }
    if ($msg -match "service|do you do|what do you|powerpoint|fan|light|switch") { return "service" }
    if ($msg -match "emergency|urgent|no power|power out|power out") { return "emergency" }
    if ($msg -match "area|where|suburb|brisbane|logan|cover") { return "area" }
    if ($msg -match "licens|insur|qualif|certif") { return "licensing" }
    return "other"
}

$misses = $results | Where-Object { -not $_.faq_hit }
$missesByCategory = $misses | Group-Object -Property { Get-MessageCategory $_.message } | Sort-Object -Property Count -Descending

# Print report
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  TEST PACK RESULTS" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Total messages: $total" -ForegroundColor White
Write-Host "Hits: $hits" -ForegroundColor Green
Write-Host "Misses: $misses" -ForegroundColor Red
Write-Host "Hit rate: $hitRate%" -ForegroundColor $(if ($hitRate -ge 75) { "Green" } elseif ($hitRate -ge 50) { "Yellow" } else { "Red" })
Write-Host ""
Write-Host "Branch breakdown:" -ForegroundColor Cyan
foreach ($branch in $branchCounts) {
    Write-Host "  $($branch.branch): $($branch.count) ($($branch.percentage)%)" -ForegroundColor White
}
Write-Host ""
Write-Host "Should miss analysis:" -ForegroundColor Cyan
Write-Host "  Total 'should miss' messages: $shouldMissTotal" -ForegroundColor White
Write-Host "  Wrong hits: $shouldMissHits" -ForegroundColor $(if ($shouldMissHits -eq 0) { "Green" } else { "Red" })
Write-Host "  Wrong hit rate: $wrongHitRate%" -ForegroundColor $(if ($wrongHitRate -eq 0) { "Green" } else { "Red" })
Write-Host ""
Write-Host "Top 10 lowest scores among HITs:" -ForegroundColor Cyan
if ($lowestScores.Count -gt 0) {
    foreach ($item in $lowestScores) {
        $msgPreview = if ($item.message) { $item.message.Substring(0, [Math]::Min(50, $item.message.Length)) } else { "N/A" }
        Write-Host "  Score: $($item.retrieval_score) | Branch: $($item.debug_branch) | '$msgPreview'" -ForegroundColor Yellow
    }
} else {
    Write-Host "  No hits with scores found" -ForegroundColor Gray
}
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  MISS ANALYSIS" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Misses by category:" -ForegroundColor Yellow
foreach ($cat in $missesByCategory) {
    Write-Host "  $($cat.Name): $($cat.Count) misses" -ForegroundColor White
}
Write-Host ""
foreach ($cat in $missesByCategory) {
    Write-Host "--- $($cat.Name.ToUpper()) MISSES ($($cat.Count)) ---" -ForegroundColor Cyan
    foreach ($miss in $cat.Group) {
        Write-Host "`n  Message: '$($miss.message)'" -ForegroundColor Yellow
        Write-Host "    Branch: $($miss.debug_branch) | Score: $($miss.retrieval_score)" -ForegroundColor Gray
        Write-Host "    Normalized: '$($miss.normalized_input)'" -ForegroundColor Gray
        
        if ($miss.candidates -and $miss.candidates.Count -gt 0) {
            Write-Host "    Top candidates:" -ForegroundColor White
            foreach ($cand in $miss.candidates) {
                Write-Host "      #$($cand.faq_id) | Score: $($cand.score) | '$($cand.question)'" -ForegroundColor Gray
            }
        } else {
            Write-Host "    No candidates found" -ForegroundColor Red
        }
        
        if ($miss.rerank_triggered) {
            Write-Host "    Rerank triggered: YES" -ForegroundColor Yellow
            if ($miss.rerank_candidates) {
                Write-Host "    Rerank saw:" -ForegroundColor White
                foreach ($rc in $miss.rerank_candidates) {
                    Write-Host "      #$($rc.index) | Score: $($rc.score) | '$($rc.question)'" -ForegroundColor Gray
                }
            }
            if ($miss.rerank_failure_reason) {
                Write-Host "    Rerank failure: $($miss.rerank_failure_reason)" -ForegroundColor Red
            } elseif ($miss.rerank_reason) {
                Write-Host "    Rerank reason: $($miss.rerank_reason)" -ForegroundColor Gray
            } else {
                Write-Host "    Rerank returned 'none'" -ForegroundColor Red
            }
        } else {
            Write-Host "    Rerank triggered: NO" -ForegroundColor Gray
        }
    }
    Write-Host ""
}
Write-Host ""
Write-Host "Full results saved to: $resultsFile" -ForegroundColor Green
Write-Host ""
