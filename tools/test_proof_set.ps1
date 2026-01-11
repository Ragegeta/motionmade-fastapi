param(
    [Parameter(Mandatory=$false)]
    [string]$TenantId = "sparkys_electrical"
)

$ErrorActionPreference = "Stop"

# Get admin token from .env
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

$renderUrl = "https://motionmade-fastapi.onrender.com"

# Test sets
$mustMiss = @(
    "can you fix my gas heater",
    "gas stove not lighting",
    "install solar panels",
    "need air con repaired",
    "toilet leaking plumber",
    "paint my house",
    "hi",
    "help",
    "???"
)

$mustHit = @(
    "smoke alarm beeping",
    "safety switch keeps tripping",
    "need a new powerpoint installed",
    "emergency no power"
)

function Invoke-DebugQuery {
    param(
        [string]$CustomerMessage,
        [int]$MaxRetries = 3
    )
    
    $body = @{
        tenantId = $TenantId
        customerMessage = $CustomerMessage
    } | ConvertTo-Json -Compress
    
    $uri = "$renderUrl/admin/api/tenant/$TenantId/debug-query"
    $headers = @{
        "Authorization" = "Bearer $token"
        "Content-Type" = "application/json"
    }
    
    $attempt = 0
    while ($attempt -lt $MaxRetries) {
        try {
            $response = Invoke-RestMethod -Uri $uri -Method POST -Headers $headers -Body $body -ErrorAction Stop
            return $response
        } catch {
            $attempt++
            if ($attempt -ge $MaxRetries) {
                Write-Host "Error: Failed after $MaxRetries attempts: $_" -ForegroundColor Red
                throw
            }
            if ($_.Exception.Message -match "timeout|connection closed|connection.*reset") {
                Write-Host "  Retry $attempt/$MaxRetries after timeout..." -ForegroundColor Yellow
                Start-Sleep -Milliseconds 400
            } else {
                throw
            }
        }
    }
}

Write-Host "`n=== PROOF SET TEST ===" -ForegroundColor Cyan
Write-Host "Tenant: $TenantId" -ForegroundColor Gray
Write-Host "URL: $renderUrl`n" -ForegroundColor Gray

$missPassed = 0
$missFailed = @()

Write-Host "[MUST MISS]" -ForegroundColor Yellow
foreach ($msg in $mustMiss) {
    try {
        $result = Invoke-DebugQuery -CustomerMessage $msg
        $hit = $result.faq_hit -eq $true
        $passed = -not $hit
        
        if ($passed) {
            $missPassed++
            $icon = "✅"
        } else {
            $missFailed += $msg
            $icon = "❌"
        }
        
        $stage = if ($result.retrieval_stage) { $result.retrieval_stage } else { "?" }
        $branch = if ($result.debug_branch) { $result.debug_branch } else { "?" }
        $score = if ($result.retrieval_score) { $result.retrieval_score } else { "?" }
        
        Write-Host "$icon | expect=MISS | hit=$hit | stage=$stage | branch=$branch | score=$score | `"$msg`"" -ForegroundColor $(if ($passed) { "Green" } else { "Red" })
        
        Start-Sleep -Milliseconds 200
    } catch {
        Write-Host "❌ | expect=MISS | ERROR: $_ | `"$msg`"" -ForegroundColor Red
        $missFailed += $msg
    }
}

$hitPassed = 0
$hitFailed = @()

Write-Host "`n[MUST HIT]" -ForegroundColor Yellow
foreach ($msg in $mustHit) {
    try {
        $result = Invoke-DebugQuery -CustomerMessage $msg
        $hit = $result.faq_hit -eq $true
        $passed = $hit
        
        if ($passed) {
            $hitPassed++
            $icon = "✅"
        } else {
            $hitFailed += $msg
            $icon = "❌"
        }
        
        $stage = if ($result.retrieval_stage) { $result.retrieval_stage } else { "?" }
        $branch = if ($result.debug_branch) { $result.debug_branch } else { "?" }
        $score = if ($result.retrieval_score) { $result.retrieval_score } else { "?" }
        
        Write-Host "$icon | expect=HIT | hit=$hit | stage=$stage | branch=$branch | score=$score | `"$msg`"" -ForegroundColor $(if ($passed) { "Green" } else { "Red" })
        
        Start-Sleep -Milliseconds 200
    } catch {
        Write-Host "❌ | expect=HIT | ERROR: $_ | `"$msg`"" -ForegroundColor Red
        $hitFailed += $msg
    }
}

Write-Host "`n=== SUMMARY ===" -ForegroundColor Cyan
Write-Host "Must-miss passed: $missPassed/$($mustMiss.Count)" -ForegroundColor $(if ($missPassed -eq $mustMiss.Count) { "Green" } else { "Red" })
Write-Host "Must-hit passed: $hitPassed/$($mustHit.Count)" -ForegroundColor $(if ($hitPassed -eq $mustHit.Count) { "Green" } else { "Red" })

if ($missFailed.Count -gt 0) {
    Write-Host "`nFailed must-miss queries:" -ForegroundColor Red
    foreach ($msg in $missFailed) {
        Write-Host "  - $msg" -ForegroundColor Red
    }
}

if ($hitFailed.Count -gt 0) {
    Write-Host "`nFailed must-hit queries:" -ForegroundColor Red
    foreach ($msg in $hitFailed) {
        Write-Host "  - $msg" -ForegroundColor Red
    }
}

if ($missPassed -eq $mustMiss.Count -and $hitPassed -eq $mustHit.Count) {
    Write-Host "`n✅ ALL TESTS PASSED" -ForegroundColor Green
    exit 0
} else {
    Write-Host "`n❌ SOME TESTS FAILED" -ForegroundColor Red
    exit 1
}

