# Rollback — MotionMade API (Render)

## Rollback trigger
- Any test-suite.ps1 test fails (especially business -> general_ok).

## Rollback steps
1) Render dashboard -> motionmade-fastapi service -> Deploys
2) Select previous successful deploy
3) Redeploy / Rollback (Render UI wording varies)

## Verify
Run:
powershell -ExecutionPolicy Bypass -NoProfile -File C:\MM\motionmade-fastapi\test-suite.ps1

All PASS = rollback confirmed.

## Render env vars reminder
Required:
- DATABASE_URL
- OPENAI_API_KEY
- ADMIN_TOKEN
- EMBED_MODEL
- CHAT_MODEL
