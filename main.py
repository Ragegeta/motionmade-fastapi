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
            # Print full traceback into Render logs
            traceback.print_exc()

            # Build a minimal "where" without dumping full stack to users
            last = ""
            try:
                tb = traceback.extract_tb(e.__traceback__)
                if tb:
                    fr = tb[-1]
                    last = f"{fr.filename}:{fr.lineno}:{fr.name}"
            except Exception:
                pass

            resp = PlainTextResponse("Internal Server Error", status_code=500)
            resp.headers["X-Exception"] = type(e).__name__
            resp.headers["X-Exception-Repr"] = (repr(e) or "")[:220]
            resp.headers["X-Trace-Last"] = last[:220]

        resp.headers["X-Git-Sha"] = os.getenv("RENDER_GIT_COMMIT", "")

        resp.headers["X-Build"] = os.getenv("BUILD_ID","")
        resp.headers["X-Entrypoint"] = "root.main"
        return resp


app.add_middleware(ProofAndCrashShield)