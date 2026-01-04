# Standardized Onboarding Solution

## Overview
Created unified onboarding script that automates:
1. FAQ upload to staging
2. Automatic variant expansion (during promote)
3. Suite + benchmark gates
4. Worker D1 domain routing
5. Install snippet generation

## Files Created/Modified

### 1. tools/onboard_tenant.ps1 (NEW)
Single command onboarding script with:
- Automatic variant expansion (via promote endpoint)
- Benchmark gate enforcement
- Worker D1 domain setup
- Fallback handling for 404 routes

### 2. app/main.py (MODIFIED)
- Added /admin/api/health endpoint for route verification

## Usage

### Basic Onboarding
`powershell
.\tools\onboard_tenant.ps1 
    -TenantId "acme_clean" 
    -Domains @("acmecleaning.com.au") 
    -FaqPath "tenants\acme_clean\faqs.json" 
    -AdminBase "https://motionmade-fastapi.onrender.com" 
    -WorkerDbName "motionmade_creator_enquiries" 
    -WorkerBackendPath "C:\MM\10__CLIENTS\client1\backend"
`

### With Custom Branding
`powershell
.\tools\onboard_tenant.ps1 
    -TenantId "acme_clean" 
    -Domains @("acmecleaning.com.au") 
    -FaqPath "tenants\acme_clean\faqs.json" 
    -BusinessName "Acme Cleaning Services" 
    -PrimaryColor "#2563eb" 
    -Greeting "Hi! How can we help?"
`

## Features

### Automatic Variant Expansion
- Variants expand automatically during promote (line 1470 in main.py)
- Uses expand_variants_inline() function
- No manual expansion needed

### Benchmark Gate
- Enforces >=75% hit rate
- Enforces 0% non-junk fallback
- Enforces 0% wrong hits
- Fails onboarding if thresholds not met

### Worker Domain Routing
- Automatically adds domains to Worker D1
- Uses wrangler d1 execute --remote
- Handles multiple domains

### Fallback Handling
- Falls back to direct upload if staged endpoint 404
- Warns but continues if promote endpoint unavailable
- Provides clear next steps

## Next Steps

1. Deploy latest code to Render (fixes 404 routes)
2. Test with sparkys_electrical
3. Verify Worker domain routing works
4. Document for customer onboarding team
