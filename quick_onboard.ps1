#Requires -Version 5.1
<#
.SYNOPSIS
    Quick onboard a new tenant with minimal friction.
.EXAMPLE
    .\quick_onboard.ps1 -TenantId "acme_clean" -Domain "acmecleaning.com.au"
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$TenantId,
    
    [Parameter(Mandatory=$true)]
    [string]$Domain,
    
    [Parameter(Mandatory=$false)]
    [string]$BusinessName = ""
)

$ErrorActionPreference = "Stop"
$scriptDir = $PSScriptRoot
$tenantDir = Join-Path $scriptDir "tenants" $TenantId

# Load token
$token = (Get-Content (Join-Path $scriptDir ".env") | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
$baseUrl = "https://motionmade-fastapi.onrender.com"
$headers = @{"Authorization"="Bearer $token"; "Content-Type"="application/json"}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  QUICK ONBOARD: $TenantId" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Step 1: Create directories
Write-Host "`n[1] Creating directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path $tenantDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $scriptDir "tests") -Force | Out-Null
Write-Host "  ✅ Created $tenantDir"

# Step 2: Create starter FAQs
$faqsPath = Join-Path $tenantDir "faqs.json"
if (-not (Test-Path $faqsPath)) {
    Write-Host "`n[2] Creating starter FAQs..." -ForegroundColor Yellow
    
    $starterFaqs = @(
        @{
            question = "Pricing and quotes"
            answer = "Our pricing depends on the type of service and your specific requirements. Could you tell me what you're looking for? I'll give you accurate pricing."
            variants = @("prices","pricing","how much","cost","quote","rates","ur prices","ur prices pls","how much u charge","wat do u charge")
        },
        @{
            question = "Services offered"
            answer = "We offer [LIST YOUR SERVICES HERE]. What service are you interested in?"
            variants = @("services","what do you do","wat do u do","what services","do you do")
        },
        @{
            question = "Service area"
            answer = "We service [YOUR AREA]. Let me know your suburb and I can confirm if we cover your location."
            variants = @("areas","suburbs","where","service area","do you come to","wat areas do u cover")
        },
        @{
            question = "Booking"
            answer = "You can book by replying here or calling us. We typically have availability within [TIMEFRAME]."
            variants = @("book","booking","how do i book","availability","can u come today","can u come tomorrow","schedule")
        }
    ) | ConvertTo-Json -Depth 10
    
    $starterFaqs | Set-Content -Path $faqsPath -Encoding UTF8
    Write-Host "  ✅ Created starter FAQs"
    Write-Host "  ⚠️  EDIT $faqsPath with real business info!" -ForegroundColor Yellow
} else {
    Write-Host "`n[2] FAQs already exist at $faqsPath" -ForegroundColor Gray
}

# Step 3: Instructions
Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  NEXT STEPS" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "1. Edit FAQs:" -ForegroundColor Cyan
Write-Host "   notepad $faqsPath" -ForegroundColor White
Write-Host ""
Write-Host "2. Add domain via Admin UI:" -ForegroundColor Cyan
Write-Host "   https://motionmade-fastapi.onrender.com/admin" -ForegroundColor White
Write-Host "   → Add tenant: $TenantId" -ForegroundColor White
Write-Host "   → Add domain: $Domain" -ForegroundColor White
Write-Host ""
Write-Host "3. Upload and promote:" -ForegroundColor Cyan
Write-Host "   # Upload staged:" -ForegroundColor Gray
Write-Host "   `$body = Get-Content '$faqsPath' -Raw" -ForegroundColor White
Write-Host "   Invoke-RestMethod -Uri '$baseUrl/admin/api/tenant/$TenantId/faqs/staged' -Method PUT -Headers `$headers -Body `$body" -ForegroundColor White
Write-Host "   # Promote:" -ForegroundColor Gray
Write-Host "   Invoke-RestMethod -Uri '$baseUrl/admin/api/tenant/$TenantId/promote' -Method POST -Headers `$headers" -ForegroundColor White
Write-Host ""
Write-Host "4. Run benchmark:" -ForegroundColor Cyan
Write-Host "   python tools/run_benchmark.py $TenantId" -ForegroundColor White
Write-Host ""
Write-Host "5. Get install snippet:" -ForegroundColor Cyan
$displayName = if ($BusinessName) { $BusinessName } else { $TenantId }
Write-Host @"
<script 
  src="https://mm-client1-creator-ui.pages.dev/widget.js"
  data-greeting="Hi! How can I help?"
  data-header="$displayName"
  data-color="#2563eb"
></script>
"@ -ForegroundColor White

