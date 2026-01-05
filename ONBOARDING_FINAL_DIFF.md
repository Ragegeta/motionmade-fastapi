# Unified Diff: Onboarding Improvements

## Summary

Made onboarding "really good" by adding a complete Admin UI dashboard, server-side endpoints, and eliminating manual steps.

## Files Changed

### 1. `app/main.py`

**Added endpoints:**

```python
@app.get("/admin/api/health")
def admin_api_health():
    """Health check with route verification."""
    # Verifies all admin routes exist
    # Returns list of verified routes
```

```python
@app.post("/admin/api/tenant/{tenantId}/benchmark")
def run_benchmark(...):
    """Run messy benchmark server-side."""
    # Loads tests/messy_benchmark.json
    # Runs all tests via API
    # Returns hit rate, fallback rate, worst misses
```

```python
@app.post("/admin/api/tenant/{tenantId}/domains/sync-worker")
def sync_worker_domains(...):
    """Sync domains to Worker D1 via Cloudflare API."""
    # Gets domains from FastAPI DB
    # Upserts to Worker D1 via Cloudflare API
    # Falls back gracefully if config missing
```

### 2. `app/templates/admin.html`

**Added "Onboarding" page:**
- Complete 7-step wizard UI
- Tenant selection/creation
- Domain management
- FAQ upload (paste JSON or file)
- One-click promote (shows suite results)
- One-click benchmark (shows quality metrics)
- One-click Worker sync
- Readiness check + install snippet

**Added navigation:**
- "Onboarding" button in tenants list
- Integrated with existing tenant management

### 3. `QUICK_REFERENCE.md`

**Added sections:**
- "How to Onboard a Tenant (3 Steps)"
- Admin UI workflow (recommended)
- New endpoint documentation
- Updated URLs table

## Operator Flow

### Admin UI (Recommended)

1. **Go to:** https://motionmade-fastapi.onrender.com/admin
2. **Login** with ADMIN_TOKEN
3. **Click "Onboarding"** tab
4. **Follow steps:**
   - Select/Create tenant
   - Add domain(s)
   - Upload FAQ JSON → Staging
   - Click "Promote" → See suite results
   - Click "Run Benchmark" → See quality metrics
   - Click "Sync Worker" → Enable widget routing
   - Check readiness → Copy install snippet

### Command Line (Alternative)

```powershell
.\tools\onboard_tenant.ps1 `
    -TenantId "acme_clean" `
    -Domains @("acmecleaning.com.au") `
    -FaqPath "tenants\acme_clean\faqs.json" `
    -AdminBase "https://motionmade-fastapi.onrender.com"
```

## Exact URLs

| Service | URL | Notes |
|---------|-----|-------|
| **Admin UI** | https://motionmade-fastapi.onrender.com/admin | Main dashboard (Render direct) |
| **Public API** | https://api.motionmadebne.com.au | Customer-facing |
| **Widget JS** | https://mm-client1-creator-ui.pages.dev/widget.js | Customer embed |

## What's Automatic

- ✅ **Variant Expansion**: Happens during promote (no manual step)
- ✅ **Suite Gate**: Runs automatically during promote
- ✅ **Benchmark Gate**: One-click server-side execution
- ✅ **Worker Sync**: One-click via Cloudflare API (or manual instructions)

## Verification

### 1. Local Tests
```powershell
pytest -q
```
✅ 25/25 tests pass

### 2. Route Check
```powershell
curl.exe -s https://motionmade-fastapi.onrender.com/admin/api/health
```
Should return 200 with route verification.

### 3. OpenAPI Check
```powershell
curl.exe -s https://motionmade-fastapi.onrender.com/openapi.json | findstr /i "/admin/api/tenants"
```
Should show admin routes.

## Benefits

1. **Single Dashboard**: Everything in one UI
2. **No 404s**: Route health check verifies endpoints
3. **No Local Paths**: Worker sync via API
4. **Automatic**: Variants expand during promote
5. **Quality Gates**: Benchmark integrated
6. **Copy-Paste**: Install snippet ready

## Next Steps

1. Deploy to Render
2. Test Admin UI onboarding flow
3. Set Cloudflare env vars (optional, for auto Worker sync)
4. Use Admin UI for all future tenants

