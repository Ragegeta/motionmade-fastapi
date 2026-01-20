$ProgressPreference = "SilentlyContinue"

param(
    [string]$TenantId = "motionmade_demo",
    [string]$BaseUrl = "https://motionmade-fastapi.onrender.com"
)

$token = (Get-Content .env | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
if (-not $token) {
    Write-Host "ADMIN_TOKEN not found in .env" -ForegroundColor Red
    exit 1
}

$url = "$BaseUrl/admin/api/tenant/$TenantId/fts-rebuild"
$r = Invoke-WebRequest -Uri $url -Method POST `
    -Headers @{ "Authorization" = "Bearer $token" } -UseBasicParsing

Write-Host "Rebuild result:"
Write-Host $r.Content
