# Render Timeout Fix

## Problem

Render service timing out after commit 505c5b5:
- `curl -m 10 -i https://motionmade-fastapi.onrender.com/api/health` times out
- Service appears unresponsive

## Root Cause

**Most Likely:** Database initialization blocking startup
- `@app.on_event("startup")` runs `conn.execute(SCHEMA_SQL)` synchronously
- If DB connection is slow or unavailable, startup hangs
- Render kills the process if it doesn't respond within timeout

## Fix Applied

1. **Added `/ping` endpoint** - Fast liveness check, no DB dependency
   ```python
   @app.get("/ping")
   def ping():
       return {"ok": True}
   ```

2. **Made startup DB init non-blocking**
   - Wrapped DB initialization in try/except
   - App starts even if DB init fails
   - Logs warning but doesn't crash

## Changes Made

### 1. Added `/ping` endpoint
- No database access
- No external calls
- Returns immediately: `{"ok": true}`

### 2. Made startup resilient
- DB initialization wrapped in try/except
- App can start even if DB is slow/unavailable
- DB-dependent endpoints may fail, but `/ping` and basic endpoints work

## Verification After Deploy

```bash
# 1. Check liveness (should be fast, no timeout)
curl.exe -m 10 -i https://motionmade-fastapi.onrender.com/ping
# Expected: HTTP/1.1 200 OK {"ok": true}

# 2. Check health (may be slow if DB is slow, but should eventually respond)
curl.exe -m 10 -i https://motionmade-fastapi.onrender.com/api/health
# Expected: HTTP/1.1 200 OK {"ok": true, "gitSha": "505c5b5", ...}

# 3. Check admin UI (should work if service is up)
curl.exe -m 10 -i https://motionmade-fastapi.onrender.com/admin
# Expected: HTTP/1.1 200 OK (HTML content)
```

## Expected Results

- `/ping` → `200 OK` immediately (no timeout)
- `/api/health` → `200 OK` (may be slower if DB is slow)
- `/admin` → `200 OK` (if service is up)

## Next Steps

1. **Push the fix:**
   ```bash
   git push origin main
   ```

2. **Wait for Render to deploy** (2-5 minutes)

3. **Verify using `/ping` first:**
   ```bash
   curl.exe -m 10 -i https://motionmade-fastapi.onrender.com/ping
   ```

4. **If `/ping` works but `/api/health` times out:**
   - DB connection may be slow
   - Check Render logs for DB connection errors
   - Consider adding connection timeout to `get_conn()`

## If Still Timing Out

Check Render logs for:
- Database connection errors
- Network timeouts
- Build failures
- Memory issues

The `/ping` endpoint should work even if DB is unavailable, confirming the service is running.


