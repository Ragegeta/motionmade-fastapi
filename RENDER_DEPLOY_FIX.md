# Render Deployment Fix - Stuck on Old Commit

## Problem

Render is stuck deploying commit `a36a43f` even though:
- Local HEAD is `dba2618` (5 commits ahead)
- GitHub has latest commits pushed
- `/admin` routes return 404 (they don't exist in `a36a43f`)

## Root Cause Analysis

**Most Likely Causes (in order):**

1. **Auto-deploy disabled** - Render won't automatically deploy new commits
2. **Wrong branch configured** - Service might be tracking `master` instead of `main`
3. **Build failures** - Recent commits might have build errors, causing Render to stay on last successful deploy
4. **Manual deploy pinned** - Service might be pinned to a specific commit
5. **Wrong repository** - Service might be connected to wrong GitHub repo

## Configuration Check

### Current Setup
- **Repository**: `https://github.com/Ragegeta/motionmade-fastapi`
- **Branch**: Should be `main`
- **Entrypoint**: `main:app` (from `Procfile`)
- **Build Command**: None specified (uses default: `pip install -r requirements.txt`)
- **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### No render.yaml Found
- Service is configured manually in Render UI
- No Blueprint configuration

## Fix Steps (Render UI)

### Step 1: Verify Service Configuration

1. Go to https://dashboard.render.com
2. Click on your service: `motionmade-fastapi`
3. Go to **Settings** tab
4. Check:
   - **Repository**: Should be `Ragegeta/motionmade-fastapi`
   - **Branch**: Should be `main` (not `master`)
   - **Auto-Deploy**: Should be **ON** (green toggle)
   - **Root Directory**: Should be empty (or `.`)

### Step 2: Check Deploy History

1. Go to **Events** tab (or **Deploys**)
2. Look for:
   - Failed builds after `a36a43f`
   - "Deploy skipped" messages
   - Build errors or warnings
3. Check the latest deploy status

### Step 3: Force Manual Deploy

**Option A: Deploy Latest Commit (Recommended)**

1. Go to **Manual Deploy** dropdown (top right)
2. Select **"Deploy latest commit"**
3. Wait for build to complete (2-5 minutes)
4. Verify new commit SHA in headers

**Option B: Deploy Specific Commit**

1. Go to **Manual Deploy** dropdown
2. Select **"Deploy specific commit"**
3. Enter commit SHA: `dba2618`
4. Click **Deploy**

### Step 4: Verify Deployment

After deploy completes, verify:

```bash
# Check git SHA in health endpoint
curl -s https://motionmade-fastapi.onrender.com/api/health | jq .gitSha
# Expected: "dba2618" (or similar, not "a36a43f")

# Check admin routes work
curl -i https://motionmade-fastapi.onrender.com/admin
# Expected: HTTP/1.1 200 OK

curl -i https://motionmade-fastapi.onrender.com/admin/api/health
# Expected: HTTP/1.1 200 OK {"ok": true, ...}
```

## Enhanced Git SHA Detection

Added fallback mechanism:
1. **Primary**: `RENDER_GIT_COMMIT` env var (set by Render)
2. **Secondary**: `GIT_SHA` env var
3. **Tertiary**: `.build-info.py` file (generated at build time)
4. **Fallback**: "unknown"

The build script (`build.sh`) captures git SHA during build and writes it to `.build-info.py`, so even if Render doesn't inject the env var, we can still detect the deployed commit.

## Minimum Steps to Fix (Click-by-Click)

1. **Go to Render Dashboard**: https://dashboard.render.com
2. **Click service**: `motionmade-fastapi`
3. **Click "Manual Deploy"** (top right, dropdown)
4. **Select "Deploy latest commit"**
5. **Wait 2-5 minutes** for build to complete
6. **Verify**: `curl -s https://motionmade-fastapi.onrender.com/api/health | jq .gitSha`

If that doesn't work:
1. Go to **Settings** tab
2. Check **Branch** is set to `main`
3. Toggle **Auto-Deploy** OFF then ON
4. Go back to **Manual Deploy** → **Deploy latest commit**

## Verification Commands

```bash
# 1. Check deployed commit SHA
curl -s https://motionmade-fastapi.onrender.com/api/health | jq .gitSha
# Should show: "dba2618" or similar (NOT "a36a43f")

# 2. Check admin UI works
curl -i https://motionmade-fastapi.onrender.com/admin
# Should show: HTTP/1.1 200 OK with HTML content

# 3. Check admin API health
curl -i https://motionmade-fastapi.onrender.com/admin/api/health
# Should show: HTTP/1.1 200 OK {"ok": true, ...}

# 4. Check admin API tenants (should be 401, not 404)
curl -i https://motionmade-fastapi.onrender.com/admin/api/tenants
# Should show: HTTP/1.1 401 Unauthorized (NOT 404)

# 5. Check routes endpoint (with auth)
curl -s https://motionmade-fastapi.onrender.com/admin/api/routes \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.total'
# Should show: 29 (or similar number of routes)
```

## If Manual Deploy Doesn't Work

1. **Check Build Logs**:
   - Go to **Events** tab
   - Click on latest deploy
   - Check for build errors

2. **Check Service Settings**:
   - Verify repository URL is correct
   - Verify branch is `main`
   - Check if there's a build command override

3. **Try Redeploy**:
   - Go to **Settings**
   - Click **"Clear build cache"**
   - Then **Manual Deploy** → **Deploy latest commit**

4. **Contact Render Support** if still stuck

## Prevention

To prevent this in the future:
1. Keep **Auto-Deploy** enabled
2. Monitor **Events** tab for failed builds
3. Use the enhanced git SHA detection (now includes build-time capture)
4. Set up webhook notifications for failed deploys


