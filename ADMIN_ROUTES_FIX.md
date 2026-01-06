# Admin Routes 404 Fix - Diagnosis & Solution

## Problem

Render deploy at commit `a36a43f` returns 404 for:
- `GET /admin`
- `GET /admin/api/health`
- `GET /admin/api/tenants`

## Root Cause

**Entrypoint mismatch is NOT the issue.** The entrypoint is correct:
- Render serves: `main:app` (from `main.py`)
- `main.py` correctly imports: `from app.main import app`
- Routes are properly registered in `app/main.py`

**The actual issue:** The deployed commit `a36a43f` doesn't contain the admin routes. They were added in later commits:
- `a36a43f` (deployed): Only contains `QUICK_REFERENCE.md`, `V1_LAUNCH_CHECKLIST.md`, `verify_v1_launch.ps1`
- `cec017a` (later): "Make onboarding really good" - adds admin routes

## Verification

### Current Codebase (HEAD)
```bash
python -c "from main import app; routes = [r.path for r in app.routes if hasattr(r, 'path')]; print(f'Total: {len(routes)}'); admin = [r for r in routes if '/admin' in r]; print(f'Admin routes: {len(admin)}')"
```
✅ **29 total routes, 18 admin routes**

### Deployed Commit (a36a43f)
```bash
git show a36a43f:app/main.py | grep -c "@app.get.*'/admin"
```
❌ **0 admin routes found**

## Solution

1. ✅ **Routes are properly registered** in current codebase
2. ✅ **Entrypoint is correct** (`main.py` imports `app.main.app`)
3. ✅ **Added debug endpoint** `/admin/api/routes` (requires auth)
4. ✅ **Added production tests** to prevent regression

## Changes Made

### 1. Added `/admin/api/routes` endpoint
```python
@app.get("/admin/api/routes")
def list_routes(authorization: str = Header(default="")):
    """List all registered routes (admin token required)."""
    _check_admin_auth(authorization)
    # Returns list of all routes
```

### 2. Added production tests
- `test_admin_ui_returns_200()` - Verifies `/admin` returns HTML
- `test_admin_api_health_returns_200()` - Verifies `/admin/api/health` works
- `test_admin_api_tenants_requires_auth()` - Verifies 401 (not 404) without auth
- `test_admin_api_routes_exists()` - Verifies routes endpoint exists

## Expected Results After Deploy

### Before (current deployed commit a36a43f)
```bash
curl -i https://motionmade-fastapi.onrender.com/admin
# HTTP/1.1 404 Not Found

curl -i https://motionmade-fastapi.onrender.com/admin/api/health
# HTTP/1.1 404 Not Found

curl -i https://motionmade-fastapi.onrender.com/admin/api/tenants
# HTTP/1.1 404 Not Found
```

### After (deploy latest commit)
```bash
curl -i https://motionmade-fastapi.onrender.com/admin
# HTTP/1.1 200 OK
# Content-Type: text/html; charset=utf-8
# <html>...</html>

curl -i https://motionmade-fastapi.onrender.com/admin/api/health
# HTTP/1.1 200 OK
# Content-Type: application/json
# {"ok": true, "routes": "available", ...}

curl -i https://motionmade-fastapi.onrender.com/admin/api/tenants
# HTTP/1.1 401 Unauthorized
# {"detail": "Unauthorized"}

curl -s https://motionmade-fastapi.onrender.com/admin/api/routes \
  -H "Authorization: Bearer $ADMIN_TOKEN" | head
# {"total": 29, "routes": [{"method": "GET", "path": "/admin"}, ...]}
```

## Next Steps

1. **Push to trigger Render deploy:**
   ```bash
   git push origin main
   ```

2. **Wait for Render to deploy** (usually 2-5 minutes)

3. **Verify routes are live:**
   ```bash
   curl -i https://motionmade-fastapi.onrender.com/admin/api/health
   ```

4. **Use debug endpoint to verify:**
   ```bash
   curl -s https://motionmade-fastapi.onrender.com/admin/api/routes \
     -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.routes[] | select(.path | startswith("/admin"))'
   ```

## Test Results

✅ **31/31 tests pass** (including 6 new production route tests)

## Summary

- **Issue:** Deployed commit doesn't have admin routes
- **Fix:** Routes are already in current code, just need to deploy
- **Prevention:** Added tests that fail if routes don't exist
- **Debug:** Added `/admin/api/routes` endpoint to verify deployed routes


