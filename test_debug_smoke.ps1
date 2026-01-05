# Smoke test: Verify debug-query endpoint exists and returns 200 (not 404)
# This ensures the endpoint is deployed and accessible

$token = (Get-Content "C:\MM\motionmade-fastapi\.env" | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
if (-not $token) {
    Write-Host "[FAIL] ADMIN_TOKEN not found" -ForegroundColor Red
    exit 1
}

$renderUrl = "https://motionmade-fastapi.onrender.com"
$body = @{customerMessage="test"} | ConvertTo-Json -Compress

try {
    $response = Invoke-WebRequest -Uri "$renderUrl/admin/api/tenant/sparkys_electrical/debug-query" `
        -Method POST `
        -Headers @{
            "Authorization" = "Bearer $token"
            "Content-Type" = "application/json"
        } `
        -Body $body `
        -UseBasicParsing `
        -TimeoutSec 30
    
    if ($response.StatusCode -eq 200) {
        Write-Host "[PASS] Debug endpoint exists and returns 200" -ForegroundColor Green
        $json = $response.Content | ConvertFrom-Json
        $requiredFields = @("faq_hit", "debug_branch", "retrieval_score", "triage_result", "replyText")
        $missingFields = $requiredFields | Where-Object { -not $json.PSObject.Properties.Name -contains $_ }
        
        if ($missingFields.Count -eq 0) {
            Write-Host "[PASS] All required debug fields present" -ForegroundColor Green
            exit 0
        } else {
            Write-Host "[FAIL] Missing fields: $($missingFields -join ', ')" -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "[FAIL] Unexpected status code: $($response.StatusCode)" -ForegroundColor Red
        exit 1
    }
} catch {
    $statusCode = $_.Exception.Response.StatusCode.value__
    if ($statusCode -eq 404) {
        Write-Host "[FAIL] Endpoint returns 404 - not deployed yet" -ForegroundColor Red
        exit 1
    } else {
        Write-Host "[FAIL] Error: $($_.Exception.Message) (Status: $statusCode)" -ForegroundColor Red
        exit 1
    }
}

