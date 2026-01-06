# Re-apply variant expansion to live FAQs
# Fetches live FAQs → uploads to staged → promotes (triggers expansion)

param(
    [Parameter(Mandatory=$true)]
    [string]$TenantId,
    
    [Parameter(Mandatory=$false)]
    [string]$AdminBase = "https://motionmade-fastapi.onrender.com",
    
    [Parameter(Mandatory=$false)]
    [string]$PublicBase = "https://api.motionmadebne.com.au"
)

$ErrorActionPreference = "Stop"

# Load admin token
$envPath = Join-Path $PSScriptRoot ".." ".env"
if (-not (Test-Path $envPath)) {
    Write-Error "Missing .env file at $envPath"
    exit 1
}
$adminToken = (Get-Content $envPath | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
if (-not $adminToken) {
    Write-Error "ADMIN_TOKEN not found in .env"
    exit 1
}

$headers = @{
    "Authorization" = "Bearer $adminToken"
    "Content-Type" = "application/json"
}

Write-Host "`n=== RE-APPLYING VARIANT EXPANSION ===" -ForegroundColor Cyan
Write-Host "Tenant: $TenantId" -ForegroundColor Yellow
Write-Host "Admin Base: $AdminBase" -ForegroundColor Yellow

# Step 1: Fetch live FAQs from database
Write-Host "`n[1/4] Fetching live FAQs from database..." -ForegroundColor Cyan
try {
    $pythonScript = @"
from app.db import get_conn
import json

tenant_id = '$TenantId'
with get_conn() as conn:
    rows = conn.execute("""
        SELECT question, answer, variants_json 
        FROM faq_items 
        WHERE tenant_id = %s AND is_staged = false
        ORDER BY id
    """, (tenant_id,)).fetchall()
    
    faqs = []
    for row in rows:
        question, answer, variants_json = row
        variants = []
        if variants_json:
            try:
                variants = json.loads(variants_json)
            except:
                pass
        faqs.append({
            "question": question,
            "answer": answer,
            "variants": variants
        })
    
    print(json.dumps(faqs, indent=2))
"@
    
    $faqsJson = python -c $pythonScript
    $faqs = $faqsJson | ConvertFrom-Json
    
    Write-Host "  Found $($faqs.Count) live FAQs" -ForegroundColor Green
} catch {
    Write-Error "Failed to fetch live FAQs: $_"
    exit 1
}

# Step 2: Upload to staged
Write-Host "`n[2/4] Uploading to staged..." -ForegroundColor Cyan
try {
    $stagedBody = $faqs | ConvertTo-Json -Depth 10
    $stagedResult = Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$TenantId/faqs/staged" `
        -Method PUT `
        -Headers $headers `
        -Body $stagedBody `
        -ContentType "application/json"
    
    Write-Host "  Staged: $($stagedResult.staged_count) FAQs" -ForegroundColor Green
} catch {
    Write-Error "Failed to upload to staged: $_"
    exit 1
}

# Step 3: Promote (triggers variant expansion)
Write-Host "`n[3/4] Promoting (triggers variant expansion)..." -ForegroundColor Cyan
Write-Host "  This will auto-expand variants and re-embed..." -ForegroundColor Yellow
try {
    $promoteResult = Invoke-RestMethod -Uri "$AdminBase/admin/api/tenant/$TenantId/promote" `
        -Method POST `
        -Headers $headers
    
    Write-Host "  Promote result:" -ForegroundColor Green
    $promoteResult | ConvertTo-Json -Depth 5 | Write-Host
    
    if ($promoteResult.status -eq "promoted" -or $promoteResult.success) {
        Write-Host "  ✅ Promotion successful" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️ Promotion may have issues" -ForegroundColor Yellow
    }
} catch {
    Write-Error "Failed to promote: $_"
    exit 1
}

# Step 4: Verify
Write-Host "`n[4/4] Verifying..." -ForegroundColor Cyan
Write-Host "  Waiting 30 seconds for embeddings to complete..." -ForegroundColor Yellow
Start-Sleep -Seconds 30

try {
    $pythonVerify = @"
from app.db import get_conn

tenant_id = '$TenantId'
with get_conn() as conn:
    live_count = conn.execute("""
        SELECT COUNT(*) FROM faq_items 
        WHERE tenant_id = %s AND is_staged = false
    """, (tenant_id,)).fetchone()[0]
    
    variant_count = conn.execute("""
        SELECT COUNT(*) FROM faq_variants fv
        JOIN faq_items fi ON fi.id = fv.faq_id
        WHERE fi.tenant_id = %s AND fi.is_staged = false
    """, (tenant_id,)).fetchone()[0]
    
    print(f"Live FAQs: {live_count}")
    print(f"Total variants: {variant_count}")
    if live_count > 0:
        print(f"Avg variants per FAQ: {variant_count / live_count:.1f}")
"@
    
    python -c $pythonVerify
    Write-Host "  ✅ Verification complete" -ForegroundColor Green
} catch {
    Write-Host "  ⚠️ Verification failed: $_" -ForegroundColor Yellow
}

Write-Host "`n=== COMPLETE ===" -ForegroundColor Cyan
Write-Host "Variant expansion has been re-applied to live FAQs" -ForegroundColor Green

