# Unified Diff: Standardized Onboarding

## Summary

Standardized onboarding with automatic variant expansion and Worker domain routing. Single command handles everything.

## Files Changed

### 1. NEW: `tools/onboard_tenant.ps1`

Complete new file (383 lines) that:
- Uploads FAQs to staging
- Promotes (auto-expands variants, runs suite)
- Runs benchmark gate (>=75% hit, 0% fallback, 0% wrong hits)
- Adds domains to Worker D1
- Generates install snippet
- Handles 404 fallbacks gracefully

**Key Features:**
- Automatic variant expansion via promote endpoint (line 1470 in main.py)
- Benchmark gate enforcement
- Worker D1 domain setup via wrangler
- Fallback to direct upload if staged endpoint unavailable
- Clear error messages and next steps

### 2. MODIFIED: `app/main.py`

**Added health check endpoint:**
```python
@app.get("/admin/api/health")
def admin_api_health():
    """Health check for admin API routes."""
    return {"ok": True, "routes": "available"}
```

**Note:** Variant expansion already implemented at line 1470:
```python
# Expand variants
items_to_promote = expand_variants_inline(items_to_promote, max_per_faq=30)
```

### 3. NEW: `ONBOARDING_STANDARDIZATION.md`

Documentation for the new onboarding process.

## Usage

### Single Command for All Businesses

```powershell
.\tools\onboard_tenant.ps1 `
    -TenantId "acme_clean" `
    -Domains @("acmecleaning.com.au") `
    -FaqPath "tenants\acme_clean\faqs.json" `
    -AdminBase "https://motionmade-fastapi.onrender.com" `
    -WorkerDbName "motionmade_creator_enquiries" `
    -WorkerBackendPath "C:\MM\10__CLIENTS\client1\backend"
```

### With Custom Branding

```powershell
.\tools\onboard_tenant.ps1 `
    -TenantId "acme_clean" `
    -Domains @("acmecleaning.com.au") `
    -FaqPath "tenants\acme_clean\faqs.json" `
    -BusinessName "Acme Cleaning Services" `
    -PrimaryColor "#2563eb" `
    -Greeting "Hi! How can we help?"
```

## What It Does

1. **Verifies FAQ file** - Checks file exists and loads FAQs
2. **Checks API routes** - Verifies endpoints are accessible
3. **Uploads to staging** - Uses `/admin/api/tenant/{id}/faqs/staged` (falls back to direct upload if 404)
4. **Promotes** - Auto-expands variants, runs suite gate
5. **Benchmark gate** - Enforces >=75% hit rate, 0% fallback, 0% wrong hits
6. **Worker domain** - Adds domain(s) to Worker D1 via wrangler
7. **Install snippet** - Generates ready-to-use widget code

## Automatic Variant Expansion

Variants expand automatically during promote (no manual step needed):
- Uses `expand_variants_inline()` function
- Generates up to 30 variants per FAQ
- Includes slang, typos, question starters
- Happens at promote-time (line 1470 in main.py)

## Benchmark Gate

Enforces strict quality thresholds:
- **Hit rate**: >= 75%
- **Fallback rate**: == 0% (for non-junk queries)
- **Wrong hit rate**: == 0%

Onboarding fails if thresholds not met.

## Worker Domain Routing

Automatically adds domains to Worker D1:
```sql
INSERT INTO tenant_domains (domain, tenant_id, enabled, notes)
VALUES ('domain.com', 'tenant_id', 1, 'onboard_tenant.ps1')
ON CONFLICT(domain) DO UPDATE SET tenant_id=excluded.tenant_id, enabled=1;
```

Uses `wrangler d1 execute --remote` to update Worker database.

## Fallback Handling

- If staged endpoint 404: Falls back to direct upload
- If promote endpoint 404: Warns but continues (promote via Admin UI)
- Clear error messages guide next steps

## Deployment Notes

**Current Issue:** API routes returning 404 in production
- Routes exist in code
- Need to deploy latest code to Render
- Script handles 404 gracefully with fallbacks

**After Deployment:**
- `/admin/api/health` will return 200
- `/admin/api/tenant/{id}/faqs/staged` will work
- `/admin/api/tenant/{id}/promote` will work
- Full automated flow will function

## Testing

Test with sparkys_electrical:
```powershell
.\tools\onboard_tenant.ps1 `
    -TenantId "sparkys_electrical" `
    -Domains @("sparkys-electrical-test.com") `
    -FaqPath "tenants\sparkys_electrical\faqs.json" `
    -SkipWorkerDomain  # Skip if wrangler not configured
```

## Next Steps

1. Deploy latest code to Render (fixes 404 routes)
2. Test full flow with sparkys_electrical
3. Verify Worker domain routing works
4. Document for customer onboarding team

