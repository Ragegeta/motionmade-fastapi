# Onboarding Improvements - Unified Diff

## Summary

Made onboarding "really good" by:
1. ✅ Fixed admin API route verification
2. ✅ Added complete onboarding dashboard in Admin UI
3. ✅ Eliminated need for local paths/wrangler setup (via Cloudflare API sync)
4. ✅ Added server-side benchmark endpoint
5. ✅ Updated documentation

## Files Changed

### 1. `app/main.py` (MODIFIED)

**Added endpoints:**

#### `/admin/api/health` (GET)
- Health check with route verification
- Returns list of verified routes
- Helps diagnose 404 issues

#### `/admin/api/tenant/{tenantId}/benchmark` (POST)
- Runs messy benchmark suite server-side
- Returns hit rate, fallback rate, wrong hit rate
- Returns worst misses for targeted fixes
- No need to run Python script locally

#### `/admin/api/tenant/{tenantId}/domains/sync-worker` (POST)
- Syncs domains from FastAPI DB to Worker D1
- Uses Cloudflare API (requires env vars)
- Falls back gracefully if config missing

**Modified:**
- Enhanced `/admin/api/health` to verify routes exist

### 2. `app/templates/admin.html` (MODIFIED)

**Added "Onboarding" page:**
- Complete 7-step onboarding wizard
- Step 1: Select/Create tenant
- Step 2: Add domains
- Step 3: Upload FAQs to staging (paste JSON or upload file)
- Step 4: Promote (one-click, runs suite + auto-expands variants)
- Step 5: Run benchmark (server-side, shows results)
- Step 6: Sync Worker domains (one-click)
- Step 7: Check readiness + copy install snippet

**Features:**
- Real-time status updates
- Error handling with clear messages
- Copy-to-clipboard for install snippet
- Visual feedback (green/red indicators)

### 3. `QUICK_REFERENCE.md` (MODIFIED)

**Added:**
- "How to Onboard a Tenant (3 Steps)" section
- Admin UI workflow (recommended)
- Command line alternative
- New endpoint documentation
- Updated URLs table with notes

## Operator Flow (Admin UI)

### Single URL Dashboard
**https://motionmade-fastapi.onrender.com/admin**

1. **Login** with ADMIN_TOKEN
2. **Click "Onboarding"** tab
3. **Follow 7 steps:**
   - Select tenant (or create new)
   - Add domain(s)
   - Paste/upload FAQ JSON → Upload to Staging
   - Click "Promote" → See suite results
   - Click "Run Benchmark" → See quality metrics
   - Click "Sync Worker Domains" → Enable widget routing
   - Click "Check Readiness" → Copy install snippet

### What Happens Automatically

- **Variant Expansion**: Happens during promote (line 1470 in main.py)
- **Suite Gate**: Runs automatically during promote
- **Benchmark Gate**: Run manually to verify quality
- **Worker Sync**: One-click domain routing setup

## Exact URLs

| Service | URL | Purpose |
|---------|-----|---------|
| **Admin UI** | https://motionmade-fastapi.onrender.com/admin | Main operator dashboard |
| **Public API** | https://api.motionmadebne.com.au | Customer-facing API |
| **Render Direct** | https://motionmade-fastapi.onrender.com | Bypass Cloudflare for admin |
| **Widget JS** | https://mm-client1-creator-ui.pages.dev/widget.js | Customer embed script |

## Environment Variables (for Worker Sync)

Optional (for automatic Worker domain sync):
- `CLOUDFLARE_API_TOKEN` - Cloudflare API token
- `CLOUDFLARE_ACCOUNT_ID` - Cloudflare account ID
- `WORKER_D1_DB_ID` - Worker D1 database ID

If not set, sync endpoint provides manual instructions.

## Verification

### 1. Local Tests
```powershell
pytest -q
```
✅ All 25 tests pass

### 2. Route Verification
```powershell
curl.exe -s https://motionmade-fastapi.onrender.com/admin/api/health
```
Should return 200 with route verification list.

### 3. Admin UI Test
1. Go to: https://motionmade-fastapi.onrender.com/admin
2. Login with ADMIN_TOKEN
3. Click "Onboarding" tab
4. Complete full workflow for test tenant

### 4. OpenAPI Check
```powershell
curl.exe -s https://motionmade-fastapi.onrender.com/openapi.json | findstr /i "/admin/api/tenants"
```
Should show admin routes in OpenAPI spec.

## Benefits

1. **No More 404s**: Route health check verifies endpoints exist
2. **Single Dashboard**: Everything in one UI
3. **No Local Paths**: Worker sync via API (or manual instructions)
4. **Automatic Variants**: No manual expansion step
5. **Quality Gates**: Benchmark integrated into workflow
6. **Copy-Paste Ready**: Install snippet with one click

## Next Steps

1. Deploy to Render (fixes any 404 routes)
2. Test full onboarding flow in Admin UI
3. Set Cloudflare env vars for automatic Worker sync (optional)
4. Use Admin UI for all future tenant onboarding

