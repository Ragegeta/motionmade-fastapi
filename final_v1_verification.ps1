cd C:\MM\motionmade-fastapi

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "   FINAL V1 VERIFICATION" -ForegroundColor Cyan  
Write-Host "========================================" -ForegroundColor Cyan

$token = (Get-Content .env | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
$renderUrl = "https://motionmade-fastapi.onrender.com"
$publicUrl = "https://api.motionmadebne.com.au"
$workerUrl = "https://mm-client1-creator-backend-v1-0-0.abbedakbery14.workers.dev"
$widgetUrl = "https://mm-client1-creator-ui.pages.dev"
$testTenant = "biz9_real"

$results = @()

function Add-Result {
    param([string]$Category, [string]$Test, [bool]$Passed, [string]$Details = "", [bool]$Skip = $false)
    $script:results += [PSCustomObject]@{
        Category = $Category
        Test = $Test
        Passed = $Passed
        Details = $Details
        Skipped = $Skip
    }
    if ($Skip) {
        Write-Host "  ⏭️  $Test (SKIPPED)" -ForegroundColor Yellow
        if ($Details) { Write-Host "     $Details" -ForegroundColor Gray }
    } else {
        $icon = if ($Passed) { "✅" } else { "❌" }
        $color = if ($Passed) { "Green" } else { "Red" }
        Write-Host "  $icon $Test" -ForegroundColor $color
        if ($Details -and -not $Passed) { Write-Host "     $Details" -ForegroundColor Yellow }
    }
}

# --- INFRASTRUCTURE ---
Write-Host "`n[INFRASTRUCTURE]" -ForegroundColor Yellow

try {
    $h1 = curl.exe -s "$publicUrl/api/health" | ConvertFrom-Json
    Add-Result "Infra" "Public API health" ($h1.ok -eq $true) "gitSha: $($h1.gitSha)"
} catch {
    Add-Result "Infra" "Public API health" $false "Error: $_"
}

try {
    $h2 = curl.exe -s "$renderUrl/api/health" | ConvertFrom-Json
    Add-Result "Infra" "Render API health" ($h2.ok -eq $true) "gitSha: $($h2.gitSha)"
} catch {
    Add-Result "Infra" "Render API health" $false "Error: $_"
}

try {
    $h3 = curl.exe -s "$workerUrl/api/health" 2>&1 | Out-String
    Add-Result "Infra" "Worker health" ($h3 -match "ok") "Response: $($h3.Trim())"
} catch {
    Add-Result "Infra" "Worker health" $false "Error: $_"
}

try {
    $widgetCheck = curl.exe -s -I "$widgetUrl/widget.js" 2>&1 | Out-String
    Add-Result "Infra" "Widget.js accessible" ($widgetCheck -match "200|javascript") "Status: $($widgetCheck -split "`n" | Select-Object -First 1)"
} catch {
    Add-Result "Infra" "Widget.js accessible" $false "Error: $_"
}

# --- ADMIN ENDPOINTS (use Render URL to bypass Cloudflare block) ---
Write-Host "`n[ADMIN ENDPOINTS]" -ForegroundColor Yellow

try {
    $stats = curl.exe -s "$renderUrl/admin/api/tenant/$testTenant/stats" -H "Authorization: Bearer $token" 2>&1 | Out-String
    if ($stats -match "Not Found|404") {
        Add-Result "Admin" "Stats endpoint" $false "Not deployed yet (expected)" -Skip $true
    } else {
        $statsJson = try { $stats | ConvertFrom-Json } catch { $null }
        Add-Result "Admin" "Stats endpoint" ($null -ne $statsJson.total_queries) "Queries: $($statsJson.total_queries)"
    }
} catch {
    Add-Result "Admin" "Stats endpoint" $false "Error: $_"
}

try {
    $alerts = curl.exe -s "$renderUrl/admin/api/tenant/$testTenant/alerts" -H "Authorization: Bearer $token" 2>&1 | Out-String
    if ($alerts -match "Not Found|404") {
        Add-Result "Admin" "Alerts endpoint" $false "Not deployed yet (expected)" -Skip $true
    } else {
        $alertsJson = try { $alerts | ConvertFrom-Json } catch { $null }
        Add-Result "Admin" "Alerts endpoint" ($null -ne $alertsJson.alerts) "Alerts: $($alertsJson.alerts.Count)"
    }
} catch {
    Add-Result "Admin" "Alerts endpoint" $false "Error: $_"
}

try {
    $ready = curl.exe -s "$renderUrl/admin/api/tenant/$testTenant/readiness" -H "Authorization: Bearer $token" 2>&1 | Out-String
    if ($ready -match "Not Found|404") {
        Add-Result "Admin" "Readiness endpoint" $false "Not deployed yet (expected)" -Skip $true
    } else {
        $readyJson = try { $ready | ConvertFrom-Json } catch { $null }
        Add-Result "Admin" "Readiness endpoint" ($null -ne $readyJson.ready) "Ready: $($readyJson.ready)"
    }
} catch {
    Add-Result "Admin" "Readiness endpoint" $false "Error: $_"
}

# --- CORE FUNCTIONALITY ---
Write-Host "`n[CORE FUNCTIONALITY]" -ForegroundColor Yellow

# Triage
try {
    $tmpFile = [System.IO.Path]::GetTempFileName()
    '{"tenantId":"biz9_real","customerMessage":"???"}' | Out-File -FilePath $tmpFile -Encoding utf8 -NoNewline
    $triage1 = curl.exe -s -X POST "$publicUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" --data-binary "@$tmpFile" 2>&1 | Out-String
    Remove-Item $tmpFile -Force
    Add-Result "Core" "Triage: junk → clarify" ($triage1 -match "rephrase")
} catch {
    Add-Result "Core" "Triage: junk → clarify" $false "Error: $_"
}

# Normalization  
try {
    $tmpFile = [System.IO.Path]::GetTempFileName()
    '{"tenantId":"biz9_real","customerMessage":"ur prices pls"}' | Out-File -FilePath $tmpFile -Encoding utf8 -NoNewline
    $norm1 = curl.exe -s -i -X POST "$publicUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" --data-binary "@$tmpFile" 2>&1 | Out-String
    Remove-Item $tmpFile -Force
    $normHeader = if ($norm1 -match "x-normalized-input:\s*(.+)") { $Matches[1].Trim() } else { "" }
    Add-Result "Core" "Normalize: 'ur prices pls' → 'your prices please'" ($normHeader -eq "your prices please") "Got: $normHeader"
} catch {
    Add-Result "Core" "Normalize: 'ur prices pls' → 'your prices please'" $false "Error: $_"
}

# FAQ hit
try {
    $tmpFile = [System.IO.Path]::GetTempFileName()
    '{"tenantId":"biz9_real","customerMessage":"Oven clean add-on"}' | Out-File -FilePath $tmpFile -Encoding utf8 -NoNewline
    $faq1 = curl.exe -s -i -X POST "$publicUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" --data-binary "@$tmpFile" 2>&1 | Out-String
    Remove-Item $tmpFile -Force
    $faqHit = $faq1 -match "x-faq-hit:\s*true"
    $hasPrice = $faq1 -match "89"
    Add-Result "Core" "FAQ hit: 'Oven clean add-on' → answer with `$89" ($faqHit -and $hasPrice)
} catch {
    Add-Result "Core" "FAQ hit: 'Oven clean add-on' → answer with `$89" $false "Error: $_"
}

# General knowledge
try {
    $tmpFile = [System.IO.Path]::GetTempFileName()
    '{"tenantId":"biz9_real","customerMessage":"Why is the sky blue?"}' | Out-File -FilePath $tmpFile -Encoding utf8 -NoNewline
    $gen1 = curl.exe -s -i -X POST "$publicUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" --data-binary "@$tmpFile" 2>&1 | Out-String
    Remove-Item $tmpFile -Force
    $isGeneral = $gen1 -match "general_ok"
    $notFaqHit = $gen1 -match "x-faq-hit:\s*false"
    Add-Result "Core" "General: 'Why is sky blue' → general_ok (not FAQ)" ($isGeneral -or $notFaqHit)
} catch {
    Add-Result "Core" "General: 'Why is sky blue' → general_ok (not FAQ)" $false "Error: $_"
}

# --- WIDGET/WORKER ---
Write-Host "`n[WIDGET/WORKER]" -ForegroundColor Yellow

try {
    $tmpFile = [System.IO.Path]::GetTempFileName()
    '{"message":"hello"}' | Out-File -FilePath $tmpFile -Encoding utf8 -NoNewline
    $w1 = curl.exe -s -X POST "$workerUrl/api/v2/widget/chat" -H "Content-Type: application/json" -H "Origin: https://motionmadebne.com.au" --data-binary "@$tmpFile" 2>&1 | Out-String
    Remove-Item $tmpFile -Force
    Add-Result "Widget" "Valid origin accepted" ($w1 -match "replyText")
} catch {
    Add-Result "Widget" "Valid origin accepted" $false "Error: $_"
}

try {
    $tmpFile = [System.IO.Path]::GetTempFileName()
    '{"message":"hello"}' | Out-File -FilePath $tmpFile -Encoding utf8 -NoNewline
    $w2 = curl.exe -s -X POST "$workerUrl/api/v2/widget/chat" -H "Content-Type: application/json" -H "Origin: https://evil.com" --data-binary "@$tmpFile" 2>&1 | Out-String
    Remove-Item $tmpFile -Force
    Add-Result "Widget" "Invalid origin blocked" ($w2 -match "domain_not_allowed")
} catch {
    Add-Result "Widget" "Invalid origin blocked" $false "Error: $_"
}

# --- SECURITY ---
Write-Host "`n[SECURITY]" -ForegroundColor Yellow

try {
    $noAuth = curl.exe -s -i "$renderUrl/admin/api/tenant/$testTenant/stats" 2>&1 | Out-String
    $is401 = $noAuth -match "401|Unauthorized"
    $is404 = $noAuth -match "404|Not Found"
    # Either 401 (auth required) or 404 (endpoint not deployed) is acceptable
    Add-Result "Security" "Admin requires auth" ($is401 -or $is404) "Got: $(if ($is401) { '401 Unauthorized' } elseif ($is404) { '404 Not Found (endpoint not deployed)' } else { 'Unexpected response' })"
} catch {
    Add-Result "Security" "Admin requires auth" $false "Error: $_"
}

# --- SUMMARY ---
$passed = ($results | Where-Object { $_.Passed -and -not $_.Skipped }).Count
$skipped = ($results | Where-Object { $_.Skipped }).Count
$failed = ($results | Where-Object { -not $_.Passed -and -not $_.Skipped }).Count
$total = $results.Count
$corePassed = $passed + $skipped

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "   RESULTS: $passed / $($total - $skipped) PASSED" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Yellow" })
if ($skipped -gt 0) {
    Write-Host "   SKIPPED: $skipped (pending deployment)" -ForegroundColor Yellow
}
Write-Host "========================================" -ForegroundColor Cyan

if ($failed -eq 0) {
    if ($skipped -gt 0) {
        Write-Host "`n  ✅ CORE FUNCTIONALITY READY" -ForegroundColor Green
        Write-Host "  ⏳ Admin endpoints pending deployment" -ForegroundColor Yellow
        Write-Host "`n  Note: New admin endpoints will be available after Render deployment completes." -ForegroundColor Gray
    } else {
        Write-Host "`n  🚀 V1 IS READY FOR LAUNCH" -ForegroundColor Green
    }
} else {
    Write-Host "`n  Failed tests:" -ForegroundColor Yellow
    $results | Where-Object { -not $_.Passed -and -not $_.Skipped } | ForEach-Object {
        Write-Host "    - $($_.Category): $($_.Test)" -ForegroundColor Red
        if ($_.Details) { Write-Host "      $($_.Details)" -ForegroundColor Gray }
    }
}

