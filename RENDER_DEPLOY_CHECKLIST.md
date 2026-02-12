# Render Deploy Checklist

## Step 1: Git (already done)
- Repo is clean and pushed. Latest: `5e567c3 Dashboard fixes: FAQ link, embed snippet, chat edge cases`

## Step 2: Required Render Environment Variables

Set these in Render → Your Service → Environment → Environment Variables:

| Variable        | Purpose                          |
|----------------|-----------------------------------|
| `DATABASE_URL` | Neon Postgres connection string   |
| `OPENAI_API_KEY` | Embeddings + GPT-4o-mini        |
| `ADMIN_TOKEN`  | Admin panel / admin API auth      |
| `JWT_SECRET`   | Owner dashboard login (JWT signing) — **add if missing** |
| `EMBED_MODEL`  | Optional; default `text-embedding-3-small` |
| `CHAT_MODEL`   | Optional; default `gpt-4o-mini`  |
| `BUILD_ID`     | Optional; e.g. `render` or leave default |

**JWT_SECRET** is required for owner dashboard login. If you don’t have it on Render yet, copy the value from your local `.env` (do not commit it). Generate a new one if needed, e.g.:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Step 3: requirements.txt

`bcrypt` and `python-jose[cryptography]` are already in `requirements.txt`. No change needed.

## Step 4: Deploy checklist for Abbed

```
============================================
  RENDER DEPLOY CHECKLIST
============================================

1. Go to https://dashboard.render.com
2. Find your motionmade-fastapi service
3. Check Environment → Environment Variables:
   ✅ DATABASE_URL
   ✅ OPENAI_API_KEY  
   ✅ ADMIN_TOKEN
   ✅ JWT_SECRET  ← Add if missing. Value: copy from your local .env
      (or generate: python3 -c "import secrets; print(secrets.token_hex(32))")

4. If auto-deploy is on: Check if latest commit deployed
   If auto-deploy is off: Click "Manual Deploy" → "Deploy latest commit"

5. Wait for deploy to finish (watch the logs)

6. Test these URLs once live (replace with your Render URL if different):
   - https://motionmade-fastapi.onrender.com/admin
   - https://motionmade-fastapi.onrender.com/dashboard/login
   - https://motionmade-fastapi.onrender.com/widget.js
   - https://motionmade-fastapi.onrender.com/api/health

============================================
```
