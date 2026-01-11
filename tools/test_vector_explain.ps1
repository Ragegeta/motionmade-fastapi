# Test EXPLAIN ANALYZE for vector query
param(
    [string]$TenantId = "sparkys_electrical",
    [string]$AdminBase = "https://motionmade-fastapi.onrender.com"
)

$token = (Get-Content "$PSScriptRoot\..\.env" | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""

Write-Host "Testing EXPLAIN ANALYZE for vector query..." -ForegroundColor Cyan
Write-Host "Tenant: $TenantId" -ForegroundColor Yellow
Write-Host "Base: $AdminBase" -ForegroundColor Yellow

try {
    $response = Invoke-WebRequest -Uri "$AdminBase/admin/api/tenant/$TenantId/explain-vector-query" `
        -Method POST `
        -Headers @{Authorization="Bearer $token"} `
        -TimeoutSec 60
    
    $result = $response.Content | ConvertFrom-Json
    
    Write-Host "`n=== EXPLAIN ANALYZE RESULTS ===" -ForegroundColor Green
    Write-Host "Uses Index: $($result.uses_index)" -ForegroundColor $(if ($result.uses_index) { "Green" } else { "Red" })
    if ($result.index_name) {
        Write-Host "Index Name: $($result.index_name)" -ForegroundColor Green
    }
    
    Write-Host "`n=== QUERY PLAN ===" -ForegroundColor Yellow
    $result.plan_text | ForEach-Object { Write-Host $_ }
    
} catch {
    Write-Host "Error: $($_.Exception.Message)" -ForegroundColor Red
    if ($_.ErrorDetails) {
        Write-Host $_.ErrorDetails.Message -ForegroundColor Red
    }
    if ($_.Response) {
        $reader = New-Object System.IO.StreamReader($_.Response.GetResponseStream())
        $responseBody = $reader.ReadToEnd()
        Write-Host "Response: $responseBody" -ForegroundColor Red
    }
}

