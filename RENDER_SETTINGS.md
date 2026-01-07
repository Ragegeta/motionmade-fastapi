# Render Deployment Settings

## Exact Render Service Configuration

### Service Settings

1. **Service Type**: Web Service
2. **Build Command**: `pip install -r requirements.txt`
3. **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. **Health Check Path**: `/ping`
5. **Health Check Interval**: 30 seconds
6. **Health Check Timeout**: 10 seconds

### Environment Variables

**Required:**
- `DATABASE_URL` - PostgreSQL connection string
- `OPENAI_API_KEY` - OpenAI API key
- `ADMIN_TOKEN` - Bearer token for admin endpoints

**Optional (for fast startup):**
- `ENABLE_CROSS_ENCODER=false` - **Set this to `false`** (default: OFF)
  - Prevents torch/sentence-transformers from loading at startup
  - Cross-encoder will use Cohere API fallback if needed

### Procfile

The `Procfile` is already correct:
```
web: uvicorn main:app --host 0.0.0.0 --port $PORT
```

**Important**: Must use `$PORT` (Render sets this automatically).

## Verification Commands

After deploy completes, run these 3 commands:

### 1. Ping (Fast Health Check)
```bash
curl -m 5 https://motionmade-fastapi.onrender.com/ping
```

**Expected Output:**
```json
{"ok":true}
```

**Success Criteria:**
- Status: `200 OK`
- Response time: < 100ms
- No timeout

### 2. Health (Full Health Check)
```bash
curl -m 10 https://motionmade-fastapi.onrender.com/api/health
```

**Expected Output:**
```json
{
  "ok": true,
  "gitSha": "b200a41..."
}
```

**Success Criteria:**
- Status: `200 OK`
- Contains `"ok": true`
- `gitSha` matches latest commit

### 3. Routes (Admin Endpoint)
```bash
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  https://motionmade-fastapi.onrender.com/admin/api/routes
```

**Expected Output:**
```json
{
  "total": 50,
  "routes": [
    {"method": "GET", "path": "/ping"},
    {"method": "GET", "path": "/api/health"},
    ...
  ]
}
```

**Success Criteria:**
- Status: `200 OK` (not 401 or 404)
- Contains `"total"` and `"routes"` keys
- `/ping` and `/admin/api/routes` are in the list

## What Changed

### 1. Cross-Encoder is Now Optional
- **Default**: `ENABLE_CROSS_ENCODER=false` (disabled)
- Model only loads when needed (lazy-load)
- Prevents torch/sentence-transformers from blocking startup
- Falls back to Cohere API or LLM selector if unavailable

### 2. Startup is Non-Blocking
- Database initialization runs in background thread
- App starts immediately, even if DB is slow
- `/ping` works even if DB init hasn't completed

### 3. `/ping` is Fast
- No database access
- No external calls
- No heavy imports
- Guaranteed < 100ms response time

### 4. Health Check Uses `/ping`
- Render health check path: `/ping`
- Fast response prevents deploy timeouts
- `/api/health` still available for detailed checks

## Troubleshooting

**If deploy is still stuck:**
1. Check Render logs for build errors
2. Verify `ENABLE_CROSS_ENCODER=false` is set
3. Check that `/ping` responds quickly (test locally first)
4. Ensure start command uses `$PORT` (not hardcoded)

**If health check fails:**
1. Verify health check path is `/ping` (not `/api/health`)
2. Check that start command uses `$PORT`
3. Ensure `/ping` doesn't touch DB or external services

## Next Steps

1. **Set Environment Variable in Render:**
   - Go to Render Dashboard → Your Service → Environment
   - Add: `ENABLE_CROSS_ENCODER=false`
   - Save

2. **Update Health Check Path:**
   - Go to Render Dashboard → Your Service → Settings
   - Health Check Path: `/ping`
   - Save

3. **Deploy:**
   - Render should auto-deploy on push
   - Or manually trigger: "Manual Deploy → Deploy latest commit"

4. **Verify:**
   - Run the 3 curl commands above
   - All should return `200 OK`


