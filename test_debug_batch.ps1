# PowerShell-native batch test: 4 messages in a loop
# Tests multiple queries and prints one line per result

$envPath = "C:\MM\motionmade-fastapi\.env"
if (-not (Test-Path $envPath)) {
    Write-Host "Error: .env file not found at $envPath" -ForegroundColor Red
    exit 1
}

$token = (Get-Content $envPath | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
if (-not $token) {
    Write-Host "Error: ADMIN_TOKEN not found in .env file" -ForegroundColor Red
    exit 1
}

$renderUrl = "https://motionmade-fastapi.onrender.com"
$tenantId = "sparkys_electrical"

$messages = @(
    "how much do you charge",
    "ur prices pls",
    "are you licensed",
    "do you do plumbing"
)

Write-Host "`n=== BATCH TEST: 4 MESSAGES ===" -ForegroundColor Cyan
Write-Host ""

foreach ($msg in $messages) {
    $body = @{
        customerMessage = $msg
    } | ConvertTo-Json -Compress
    
    try {
        $response = Invoke-RestMethod -Uri "$renderUrl/admin/api/tenant/$tenantId/debug-query" `
            -Method POST `
            -Headers @{
                "Authorization" = "Bearer $token"
                "Content-Type" = "application/json"
            } `
            -Body $body `
            -TimeoutSec 30
        
        $hit = if ($response.faq_hit) { "HIT" } else { "MISS" }
        $branch = $response.debug_branch
        $score = if ($response.retrieval_score) { $response.retrieval_score } else { "n/a" }
        
        $color = if ($response.faq_hit) { "Green" } else { "Red" }
        Write-Host "  $hit | $branch | $score | '$msg'" -ForegroundColor $color
        
    } catch {
        Write-Host "  ERROR | ? | ? | '$msg' - $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host ""

