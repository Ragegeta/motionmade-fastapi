"""
Production entrypoint (Render).

Render runs uvicorn against: main:app
So this file must stay a thin wrapper.
"""
import os
import traceback

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

from app.main import app  # real FastAPI app lives here


class ProofAndCrashShield(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        try:
            resp = await call_next(request)
        except Exception as e:
            # Ensure the exception is visible in Render logs
            traceback.print_exc()

            # Still return a response so we can attach proof headers
            resp = PlainTextResponse("Internal Server Error", status_code=500)
            resp.headers["X-Exception"] = type(e).__name__

        resp.headers["X-Git-Sha"] = os.getenv("RENDER_GIT_COMMIT", "")
        resp.headers["X-Entrypoint"] = "root.main"
        return resp


app.add_middleware(ProofAndCrashShield)