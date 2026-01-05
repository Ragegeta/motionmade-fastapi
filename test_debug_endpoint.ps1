# PowerShell-native debug endpoint test
# Reads ADMIN_TOKEN from .env and calls debug-query endpoint

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
$customerMessage = "ur prices pls"

# Create JSON body as PowerShell hashtable, then convert to JSON
# This ensures proper JSON encoding without shell escaping issues
$body = @{
    customerMessage = $customerMessage
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
    
    Write-Host "`n=== FULL JSON RESPONSE ===" -ForegroundColor Cyan
    $response | ConvertTo-Json -Depth 10
    
    Write-Host "`n=== KEY FIELDS ===" -ForegroundColor Cyan
    Write-Host "faq_hit: $($response.faq_hit)" -ForegroundColor $(if ($response.faq_hit) { "Green" } else { "Red" })
    Write-Host "debug_branch: $($response.debug_branch)" -ForegroundColor Yellow
    Write-Host "retrieval_score: $($response.retrieval_score)" -ForegroundColor Yellow
    Write-Host "normalized_input: $($response.normalized_input)" -ForegroundColor Gray
    
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ErrorDetails) {
        Write-Host "Details: $($_.ErrorDetails.Message)" -ForegroundColor Gray
    }
    if ($_.Exception.Response) {
        $statusCode = $_.Exception.Response.StatusCode.value__
        Write-Host "Status Code: $statusCode" -ForegroundColor Red
    }
}
