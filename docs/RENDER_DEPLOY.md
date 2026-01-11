# Render Deployment Guide

## Quick Start

### Render Service Settings

1. **Service Type**: Web Service
2. **Build Command**: `pip install -r requirements.txt`
3. **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. **Health Check Path**: `/ping`
5. **Health Check Interval**: 30 seconds

### Environment Variables

**Required:**
- `DATABASE_URL` - PostgreSQL connection string
- `OPENAI_API_KEY` - OpenAI API key for embeddings/LLM
- `ADMIN_TOKEN` - Bearer token for admin endpoints

**Optional:**
- `ENABLE_CROSS_ENCODER=false` - Disable cross-encoder (default: OFF for fast startup)
- `COHERE_API_KEY` - Cohere API key (fallback if cross-encoder disabled)
- `RENDER_GIT_COMMIT` - Auto-set by Render (git SHA)
- `RENDER_GIT_BRANCH` - Auto-set by Render (branch name)

### Health Check Configuration

**Health Check Path**: `/ping`

This endpoint:
- Returns `{"ok": true}` immediately
- Does NOT touch database
- Does NOT make external calls
- Does NOT load heavy models
- Should respond in < 100ms

**Why `/ping` instead of `/api/health`?**
- `/api/health` may query database (slower)
- `/ping` is guaranteed fast (no dependencies)
- Render health checks need fast response to avoid timeouts

### Startup Behavior

The app is designed for fast, non-blocking startup:

1. **No heavy imports at module load**
   - Cross-encoder model is lazy-loaded (only when needed)
   - Database connections are lazy (only when needed)

2. **Database initialization is non-blocking**
   - Runs in background thread
   - App starts immediately, even if DB is slow
   - `/ping` works even if DB init hasn't completed

3. **Cross-encoder is optional**
   - Default: `ENABLE_CROSS_ENCODER=false` (disabled)
   - Prevents torch/sentence-transformers from loading at startup
   - Can be enabled later if needed: `ENABLE_CROSS_ENCODER=true`

### Verification Commands

After deploy, verify with these 3 commands:

```bash
# 1. Ping (should be fast, < 100ms)
curl -m 5 https://motionmade-fastapi.onrender.com/ping
# Expected: {"ok":true}

# 2. Health (may be slower, but should work)
curl -m 10 https://motionmade-fastapi.onrender.com/api/health
# Expected: {"ok":true,"gitSha":"..."}

# 3. Routes (admin token required)
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://motionmade-fastapi.onrender.com/admin/api/routes
# Expected: {"total":N,"routes":[...]}
```

### Troubleshooting

**Deploy stuck at "Deploying..."**
- Check Render logs for build errors
- Verify `requirements.txt` doesn't include heavy deps at top level
- Ensure `ENABLE_CROSS_ENCODER=false` (default)
- Check that `/ping` responds quickly

**Health check failing**
- Verify health check path is `/ping` (not `/api/health`)
- Check that start command uses `$PORT` (not hardcoded port)
- Ensure `/ping` doesn't touch DB or external services

**Slow startup**
- Check if cross-encoder is enabled (should be OFF by default)
- Verify DB init runs in background thread (non-blocking)
- Check Render logs for import-time errors

### Procfile

The `Procfile` should contain:
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

**Important**: Must use `$PORT` (Render sets this automatically).

### CI/CD Integration

The smoke test (`tests/test_ping_smoke.py`) should run in CI:

```bash
python -m pytest -q tests/test_ping_smoke.py
```

This ensures `/ping` is always fast and reliable.


