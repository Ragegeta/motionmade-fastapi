# Test Hybrid Retrieval Implementation
param(
    [string]$TenantId = "biz9_real",
    [string]$ApiUrl = "https://api.motionmadebne.com.au"
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  HYBRID RETRIEVAL TEST" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Tenant: $TenantId" -ForegroundColor Yellow
Write-Host "API: $ApiUrl" -ForegroundColor Yellow
Write-Host ""

$testQueries = @(
    "can u install ceiling fans",
    "do u do smoke alarms",
    "can you do switchboards",
    "do u service logan",
    "wat do u do",
    "urgent"
)

$results = @()

foreach ($query in $testQueries) {
    Write-Host "Testing: '$query'" -ForegroundColor Cyan
    
    $body = @{
        tenantId = $TenantId
        customerMessage = $query
    } | ConvertTo-Json -Compress
    
    $tempFile = [System.IO.Path]::GetTempFileName()
    $body | Out-File -FilePath $tempFile -Encoding UTF8
    
    try {
        $response = curl.exe -s -i -X POST "$ApiUrl/api/v2/generate-quote-reply" `
            -H "Content-Type: application/json" `
            --data-binary "@$tempFile" 2>&1
        
        # Parse headers
        $hit = $false
        $score = $null
        $stage = "?"
        $mode = "?"
        $candidates = 0
        $selectorCalled = $false
        $selectorConf = $null
        $chosenFaqId = $null
        
        if ($response -match "x-faq-hit:\s*true") {
            $hit = $true
        }
        
        if ($response -match "x-retrieval-score:\s*([\d.]+)") {
            $score = [double]$Matches[1]
        }
        
        if ($response -match "x-retrieval-stage:\s*(\S+)") {
            $stage = $Matches[1]
        }
        
        if ($response -match "x-retrieval-mode:\s*(\S+)") {
            $mode = $Matches[1]
        }
        
        if ($response -match "x-candidate-count:\s*(\d+)") {
            $candidates = [int]$Matches[1]
        }
        
        if ($response -match "x-selector-called:\s*(true|false)") {
            $selectorCalled = $Matches[1] -eq "true"
        }
        
        if ($response -match "x-selector-confidence:\s*([\d.]+)") {
            $selectorConf = [double]$Matches[1]
        }
        
        if ($response -match "x-chosen-faq-id:\s*(\d+)") {
            $chosenFaqId = [int]$Matches[1]
        }
        
        $result = [PSCustomObject]@{
            Query = $query
            Hit = $hit
            Score = $score
            Stage = $stage
            Mode = $mode
            Candidates = $candidates
            SelectorCalled = $selectorCalled
            SelectorConfidence = $selectorConf
            ChosenFaqId = $chosenFaqId
        }
        
        $results += $result
        
        $color = if ($hit) { "Green" } elseif ($candidates -gt 0) { "Yellow" } else { "Red" }
        Write-Host "  Hit: $hit | Score: $score | Stage: $stage | Mode: $mode" -ForegroundColor $color
        Write-Host "  Candidates: $candidates | Selector: $selectorCalled | Conf: $selectorConf" -ForegroundColor Gray
        if ($chosenFaqId) {
            Write-Host "  Chosen FAQ ID: $chosenFaqId" -ForegroundColor Gray
        }
        Write-Host ""
        
    } catch {
        Write-Host "  ERROR: $($_.Exception.Message)" -ForegroundColor Red
    } finally {
        Remove-Item $tempFile -ErrorAction SilentlyContinue
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  SUMMARY" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$hits = ($results | Where-Object { $_.Hit }).Count
$withCandidates = ($results | Where-Object { $_.Candidates -gt 0 }).Count
$selectorUsed = ($results | Where-Object { $_.SelectorCalled }).Count

Write-Host "Total queries: $($results.Count)" -ForegroundColor White
Write-Host "FAQ hits: $hits / $($results.Count)" -ForegroundColor $(if ($hits -gt 0) { "Green" } else { "Red" })
Write-Host "Queries with candidates: $withCandidates / $($results.Count)" -ForegroundColor $(if ($withCandidates -eq $results.Count) { "Green" } else { "Yellow" })
Write-Host "Selector called: $selectorUsed / $($results.Count)" -ForegroundColor White

Write-Host "`nDetailed results:" -ForegroundColor Yellow
$results | Format-Table -AutoSize

