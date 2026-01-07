# Production readiness test pack
# Tests 60 questions (30 should-hit, 20 should-miss, 10 edge)

param(
    [Parameter(Mandatory=$true)]
    [string]$TenantId,
    
    [Parameter(Mandatory=$false)]
    [string]$AdminBase = "https://motionmade-fastapi.onrender.com",
    
    [Parameter(Mandatory=$false)]
    [string]$PublicBase = "https://api.motionmadebne.com.au"
)

$ErrorActionPreference = "Stop"

# Load admin token
$envPath = Join-Path $PSScriptRoot ".." ".env"
if (-not (Test-Path $envPath)) {
    Write-Error "Missing .env file at $envPath"
    exit 1
}
$adminToken = (Get-Content $envPath | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
if (-not $adminToken) {
    Write-Error "ADMIN_TOKEN not found in .env"
    exit 1
}

$adminHeaders = @{
    "Authorization" = "Bearer $adminToken"
    "Content-Type" = "application/json"
}

Write-Host "`n=== PRODUCTION READINESS TEST PACK ===" -ForegroundColor Cyan
Write-Host "Tenant: $TenantId" -ForegroundColor Yellow

# Generate 60 test questions
Write-Host "`n[1/3] Generating 60 test questions..." -ForegroundColor Cyan

$questions = @()

# 30 should-hit (real electrical customer phrasing)
$shouldHit = @(
    "my smoke alarm keeps beeping can u help",
    "that beeping sound is driving me crazy",
    "smoke alarm chirping nonstop",
    "lights flicker when i turn on appliances",
    "safety switch keeps cutting power",
    "need more plugs in the kitchen",
    "ceiling fan stopped working",
    "switchboard making weird noises",
    "power went out completely",
    "lights dim when i use the dryer",
    "safety switch trips every time",
    "smoke detector battery low",
    "want to add outlets in garage",
    "old fuse box needs upgrade",
    "emergency electrician needed now",
    "can you install a fan",
    "lights keep turning off",
    "no power in half the house",
    "safety switch won't reset",
    "smoke alarm false alarms",
    "need electrical work done",
    "lights flickering constantly",
    "power point not working",
    "switchboard upgrade cost",
    "ceiling fan installation price",
    "smoke alarm replacement",
    "safety switch installation",
    "emergency call out",
    "lights dimming randomly",
    "electrical fault somewhere"
)

# 20 should-miss (wrong services)
$shouldMiss = @(
    "can you fix my air conditioner",
    "need a plumber for leak",
    "gas line installation quote",
    "solar panel installation prices",
    "security camera wiring",
    "dishwasher repair service",
    "oven not heating up",
    "need someone to paint",
    "roofing work needed",
    "carpentry services",
    "tiling installation",
    "landscaping services",
    "lawn mowing needed",
    "tree removal service",
    "fence installation",
    "concrete work needed",
    "plastering services",
    "hvac system repair",
    "split system installation",
    "intercom system wiring"
)

# 10 edge/unclear
$edgeCases = @(
    "help",
    "how much",
    "are you available",
    "what services",
    "can you come",
    "its broken",
    "urgent help",
    "when are you free",
    "whats the price",
    "need help asap"
)

foreach ($q in $shouldHit) {
    $questions += [PSCustomObject]@{ Question = $q; Expected = "hit"; Category = "should_hit" }
}
foreach ($q in $shouldMiss) {
    $questions += [PSCustomObject]@{ Question = $q; Expected = "miss"; Category = "should_miss" }
}
foreach ($q in $edgeCases) {
    $questions += [PSCustomObject]@{ Question = $q; Expected = "unclear"; Category = "edge" }
}

Write-Host "  Generated $($questions.Count) questions" -ForegroundColor Green

# Test each question
Write-Host "`n[2/3] Testing questions against production..." -ForegroundColor Cyan
$results = @()
$testNum = 0

foreach ($q in $questions) {
    $testNum++
    if ($testNum % 10 -eq 0) {
        Write-Host "  Progress: $testNum/$($questions.Count)..." -ForegroundColor Gray
    }
    
    try {
        # Use debug-query endpoint (admin) for detailed traces
        $debugBody = @{
            tenantId = $TenantId
            customerMessage = $q.Question
        } | ConvertTo-Json -Compress
        
        $debugResponse = Invoke-RestMethod -Uri "$AdminBase/admin/api/debug-query" `
            -Method POST `
            -Headers $adminHeaders `
            -Body $debugBody `
            -ContentType "application/json" `
            -ErrorAction Stop
        
        $faqHit = $debugResponse.faq_hit -eq $true
        $actual = if ($faqHit) { "hit" } elseif ($debugResponse.debug_branch -match "clarify") { "clarify" } else { "miss" }
        
        $results += [PSCustomObject]@{
            Question = $q.Question
            Expected = $q.Expected
            Category = $q.Category
            Actual = $actual
            FaqHit = $faqHit
            DebugBranch = $debugResponse.debug_branch
            RetrievalScore = $debugResponse.retrieval_score
            NormalizedInput = $debugResponse.normalized_input
            ChosenFaqId = $debugResponse.chosen_faq_id
            ChosenFaqQuestion = $debugResponse.chosen_faq_question
            CandidatesCount = $debugResponse.candidates_count
            Trace = ($debugResponse | ConvertTo-Json -Depth 5)
        }
        
        Start-Sleep -Milliseconds 200
    } catch {
        Write-Host "  ⚠️ Error testing '$($q.Question)': $_" -ForegroundColor Yellow
        $results += [PSCustomObject]@{
            Question = $q.Question
            Expected = $q.Expected
            Category = $q.Category
            Actual = "error"
            Error = $_.Exception.Message
        }
    }
}

# Save results
$resultsFile = Join-Path $PSScriptRoot ".." "production_readiness_results.json"
$results | ConvertTo-Json -Depth 10 | Set-Content -Path $resultsFile -Encoding UTF8
Write-Host "`n  Results saved to: $resultsFile" -ForegroundColor Green

# Analyze results
Write-Host "`n[3/3] Analyzing results..." -ForegroundColor Cyan

$shouldHitResults = $results | Where-Object { $_.Category -eq "should_hit" }
$shouldMissResults = $results | Where-Object { $_.Category -eq "should_miss" }
$edgeResults = $results | Where-Object { $_.Category -eq "edge" }

$hitRate = [math]::Round((($shouldHitResults | Where-Object { $_.Actual -eq "hit" }).Count / $shouldHitResults.Count) * 100, 1)
$wrongHitRate = [math]::Round((($shouldMissResults | Where-Object { $_.Actual -eq "hit" }).Count / $shouldMissResults.Count) * 100, 1)
$edgeClarifyRate = [math]::Round((($edgeResults | Where-Object { $_.Actual -ne "hit" }).Count / $edgeResults.Count) * 100, 1)

Write-Host "`n=== RESULTS ===" -ForegroundColor Cyan
Write-Host "  Hit Rate (should-hit): $hitRate% ($(($shouldHitResults | Where-Object { $_.Actual -eq 'hit' }).Count)/$($shouldHitResults.Count))" -ForegroundColor $(if ($hitRate -ge 85) { "Green" } else { "Red" })
Write-Host "  Wrong-Hit Rate (should-miss): $wrongHitRate% ($(($shouldMissResults | Where-Object { $_.Actual -eq 'hit' }).Count)/$($shouldMissResults.Count))" -ForegroundColor $(if ($wrongHitRate -eq 0) { "Green" } else { "Red" })
Write-Host "  Edge Clarify Rate: $edgeClarifyRate% ($(($edgeResults | Where-Object { $_.Actual -ne 'hit' }).Count)/$($edgeResults.Count))" -ForegroundColor $(if ($edgeClarifyRate -ge 80) { "Green" } else { "Yellow" })

# Top 10 misses
$misses = $shouldHitResults | Where-Object { $_.Actual -ne "hit" } | Select-Object -First 10
if ($misses.Count -gt 0) {
    Write-Host "`n=== TOP 10 MISSES ===" -ForegroundColor Yellow
    for ($i = 0; $i -lt $misses.Count; $i++) {
        $m = $misses[$i]
        Write-Host "`n  [$($i+1)] $($m.Question)" -ForegroundColor White
        Write-Host "      Normalized: $($m.NormalizedInput)" -ForegroundColor Gray
        Write-Host "      Score: $($m.RetrievalScore) | Branch: $($m.DebugBranch)" -ForegroundColor Gray
        Write-Host "      Candidates: $($m.CandidatesCount)" -ForegroundColor Gray
    }
}

# Scorecard
Write-Host "`n=== PRODUCTION READINESS SCORECARD ===" -ForegroundColor Cyan
$pass = $true
$issues = @()

if ($hitRate -lt 85) {
    $pass = $false
    $issues += "Hit rate $hitRate% < 85% target"
}
if ($wrongHitRate -gt 0) {
    $pass = $false
    $issues += "Wrong-hit rate $wrongHitRate% > 0% target"
}

# Check specific regression queries
$regressionQueries = @(
    "my smoke alarm keeps beeping can u help",
    "that beeping sound is driving me crazy",
    "smoke alarm chirping nonstop"
)
$regressionPass = $true
foreach ($rq in $regressionQueries) {
    $r = $results | Where-Object { $_.Question -eq $rq }
    if ($r -and $r.Actual -ne "hit") {
        $regressionPass = $false
        $issues += "Regression: '$rq' should hit but got $($r.Actual)"
    }
}

if ($regressionPass) {
    Write-Host "  ✅ Regression queries passing" -ForegroundColor Green
} else {
    $pass = $false
}

if ($pass) {
    Write-Host "`n  ✅ PRODUCTION READY" -ForegroundColor Green
    Write-Host "  System can be sold without manual variant writing" -ForegroundColor Green
} else {
    Write-Host "`n  ❌ NOT PRODUCTION READY" -ForegroundColor Red
    Write-Host "  Issues:" -ForegroundColor Yellow
    foreach ($issue in $issues) {
        Write-Host "    - $issue" -ForegroundColor Yellow
    }
}

Write-Host "`n=== COMPLETE ===" -ForegroundColor Cyan


