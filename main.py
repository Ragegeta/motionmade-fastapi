"""
Production entrypoint (Render).

Render runs uvicorn against: main:app
So this file must be the thin wrapper that:
- imports the real app from app/main.py
- adds proof headers so we can confirm what code is live
"""

import os
from app.main import app  # this is the real FastAPI app

@app.middleware("http")
async def _proof_headers(request, call_next):
    resp = await call_next(request)
    resp.headers["X-Git-Sha"] = os.getenv("RENDER_GIT_COMMIT", "")
    resp.headers["X-Entrypoint"] = "root.main"
    return resp