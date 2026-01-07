# Simplified production readiness test
param(
    [string]$TenantId = "sparkys_electrical",
    [string]$AdminBase = "https://motionmade-fastapi.onrender.com"
)

$token = (Get-Content "$PSScriptRoot\..\.env" | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
$headers = @{"Authorization" = "Bearer $token"; "Content-Type" = "application/json"}

Write-Host "`n=== PRODUCTION READINESS TEST (60 QUESTIONS) ===" -ForegroundColor Cyan

# Generate questions
$shouldHit = @(
    "my smoke alarm keeps beeping can u help", "that beeping sound is driving me crazy", "smoke alarm chirping nonstop",
    "lights flicker when i turn on appliances", "safety switch keeps cutting power", "need more plugs in the kitchen",
    "ceiling fan stopped working", "switchboard making weird noises", "power went out completely", "lights dim when i use the dryer",
    "safety switch trips every time", "smoke detector battery low", "want to add outlets in garage", "old fuse box needs upgrade",
    "emergency electrician needed now", "can you install a fan", "lights keep turning off", "no power in half the house",
    "safety switch won't reset", "smoke alarm false alarms", "need electrical work done", "lights flickering constantly",
    "power point not working", "switchboard upgrade cost", "ceiling fan installation price", "smoke alarm replacement",
    "safety switch installation", "emergency call out", "lights dimming randomly", "electrical fault somewhere"
)

$shouldMiss = @(
    "can you fix my air conditioner", "need a plumber for leak", "gas line installation quote", "solar panel installation prices",
    "security camera wiring", "dishwasher repair service", "oven not heating up", "need someone to paint", "roofing work needed",
    "carpentry services", "tiling installation", "landscaping services", "lawn mowing needed", "tree removal service",
    "fence installation", "concrete work needed", "plastering services", "hvac system repair", "split system installation",
    "intercom system wiring"
)

$edgeCases = @("help", "how much", "are you available", "what services", "can you come", "its broken", "urgent help", "when are you free", "whats the price", "need help asap")

$questions = @()
foreach ($q in $shouldHit) { $questions += [PSCustomObject]@{ Question = $q; Expected = "hit"; Category = "should_hit" } }
foreach ($q in $shouldMiss) { $questions += [PSCustomObject]@{ Question = $q; Expected = "miss"; Category = "should_miss" } }
foreach ($q in $edgeCases) { $questions += [PSCustomObject]@{ Question = $q; Expected = "unclear"; Category = "edge" } }

Write-Host "Testing $($questions.Count) questions...`n" -ForegroundColor Yellow

$results = @()
$testNum = 0

foreach ($q in $questions) {
    $testNum++
    if ($testNum % 10 -eq 0) { Write-Host "  Progress: $testNum/$($questions.Count)..." -ForegroundColor Gray }
    
    try {
        $body = @{tenantId = $TenantId; customerMessage = $q.Question} | ConvertTo-Json -Compress
        $r = Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$TenantId/debug-query" -Method POST -Headers $headers -Body $body -ErrorAction Stop
        
        $faqHit = $r.faq_hit -eq $true
        $actual = if ($faqHit) { "hit" } elseif ($r.debug_branch -match "clarify") { "clarify" } else { "miss" }
        
        $results += [PSCustomObject]@{
            Question = $q.Question
            Expected = $q.Expected
            Category = $q.Category
            Actual = $actual
            FaqHit = $faqHit
            DebugBranch = $r.debug_branch
            RetrievalScore = $r.retrieval_score
            NormalizedInput = $r.normalized_input
            ChosenFaqId = $r.chosen_faq_id
            ChosenFaqQuestion = $r.chosen_faq_question
            CandidatesCount = $r.candidates_count
        }
        
        Start-Sleep -Milliseconds 200
    } catch {
        Write-Host "  ⚠️ Error: $_" -ForegroundColor Yellow
        $results += [PSCustomObject]@{ Question = $q.Question; Expected = $q.Expected; Category = $q.Category; Actual = "error"; Error = $_.Exception.Message }
    }
}

# Save results
$resultsFile = "$PSScriptRoot\..\production_readiness_results.json"
$results | ConvertTo-Json -Depth 10 | Set-Content -Path $resultsFile -Encoding UTF8
Write-Host "`nResults saved to: $resultsFile" -ForegroundColor Green

# Analyze
$shouldHitResults = $results | Where-Object { $_.Category -eq "should_hit" }
$shouldMissResults = $results | Where-Object { $_.Category -eq "should_miss" }
$edgeResults = $results | Where-Object { $_.Category -eq "edge" }

$hitRate = [math]::Round((($shouldHitResults | Where-Object { $_.Actual -eq "hit" }).Count / $shouldHitResults.Count) * 100, 1)
$wrongHitRate = [math]::Round((($shouldMissResults | Where-Object { $_.Actual -eq "hit" }).Count / $shouldMissResults.Count) * 100, 1)
$edgeClarifyRate = [math]::Round((($edgeResults | Where-Object { $_.Actual -ne "hit" }).Count / $edgeResults.Count) * 100, 1)

Write-Host "`n=== RESULTS ===" -ForegroundColor Cyan
Write-Host "  Hit Rate: $hitRate% ($(($shouldHitResults | Where-Object { $_.Actual -eq 'hit' }).Count)/$($shouldHitResults.Count))" -ForegroundColor $(if ($hitRate -ge 85) { "Green" } else { "Red" })
Write-Host "  Wrong-Hit Rate: $wrongHitRate% ($(($shouldMissResults | Where-Object { $_.Actual -eq 'hit' }).Count)/$($shouldMissResults.Count))" -ForegroundColor $(if ($wrongHitRate -eq 0) { "Green" } else { "Red" })
Write-Host "  Edge Clarify Rate: $edgeClarifyRate%" -ForegroundColor $(if ($edgeClarifyRate -ge 80) { "Green" } else { "Yellow" })

# Top 10 misses
$misses = $shouldHitResults | Where-Object { $_.Actual -ne "hit" } | Select-Object -First 10
if ($misses.Count -gt 0) {
    Write-Host "`n=== TOP 10 MISSES ===" -ForegroundColor Yellow
    for ($i = 0; $i -lt $misses.Count; $i++) {
        $m = $misses[$i]
        Write-Host "`n  [$($i+1)] $($m.Question)" -ForegroundColor White
        Write-Host "      Normalized: $($m.NormalizedInput)" -ForegroundColor Gray
        Write-Host "      Score: $($m.RetrievalScore) | Branch: $($m.DebugBranch)" -ForegroundColor Gray
    }
}

# Scorecard
Write-Host "`n=== PRODUCTION READINESS SCORECARD ===" -ForegroundColor Cyan
$pass = ($hitRate -ge 85) -and ($wrongHitRate -eq 0)

# Check regression queries
$regressionQueries = @("my smoke alarm keeps beeping can u help", "that beeping sound is driving me crazy", "smoke alarm chirping nonstop")
$regressionPass = $true
foreach ($rq in $regressionQueries) {
    $r = $results | Where-Object { $_.Question -eq $rq }
    if ($r -and $r.Actual -ne "hit") {
        $regressionPass = $false
        Write-Host "  ❌ Regression: '$rq' should hit but got $($r.Actual)" -ForegroundColor Red
    }
}

if ($regressionPass) {
    Write-Host "  ✅ Regression queries passing" -ForegroundColor Green
}

if ($pass -and $regressionPass) {
    Write-Host "`n  ✅ PRODUCTION READY" -ForegroundColor Green
    Write-Host "  System can be sold without manual variant writing" -ForegroundColor Green
} else {
    Write-Host "`n  ❌ NOT PRODUCTION READY" -ForegroundColor Red
    if ($hitRate -lt 85) { Write-Host "    - Hit rate $hitRate% < 85%" -ForegroundColor Yellow }
    if ($wrongHitRate -gt 0) { Write-Host "    - Wrong-hit rate $wrongHitRate% > 0%" -ForegroundColor Yellow }
}

Write-Host "`n=== COMPLETE ===" -ForegroundColor Cyan


