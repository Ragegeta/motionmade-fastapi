import re
from pathlib import Path

p = Path("app/main.py")
t = p.read_text(encoding="utf-8")

# 1) Ensure imports
if "import os" not in t:
    t = "import os\n" + t

# Ensure Request import exists
if re.search(r"from fastapi import .*Request", t) is None:
    # if there's already "from fastapi import ..." line, extend it
    m = re.search(r"^from fastapi import (.+)$", t, flags=re.M)
    if m:
        existing = m.group(1).strip()
        if "Request" not in existing.split(","):
            new = existing + ", Request"
            t = t[:m.start()] + f"from fastapi import {new}\n" + t[m.end():]
    else:
        t = t.replace("import os\n", "import os\nfrom fastapi import Request\n", 1)

# 2) Insert middleware right after app = FastAPI()
middleware_snip = r'''
@app.middleware("http")
async def add_release_headers(request: Request, call_next):
    resp = await call_next(request)
    git_sha = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_SHA") or "unknown"
    release = os.getenv("RENDER_GIT_BRANCH") or os.getenv("RELEASE") or "unknown"
    resp.headers["x-git-sha"] = git_sha
    resp.headers["x-release"] = release
    return resp
'''.lstrip("\n")

if 'resp.headers["x-git-sha"]' not in t:
    m = re.search(r"^app\s*=\s*FastAPI\([^\)]*\)\s*$", t, flags=re.M)
    if not m:
        raise SystemExit("Could not find `app = FastAPI(...)` in app/main.py")
    insert_at = m.end()
    t = t[:insert_at] + "\n\n" + middleware_snip + "\n" + t[insert_at:]

# 3) Add /api/health (idempotent)
if re.search(r'@app\.(get|api_route)\(["\']\/api\/health["\']', t) is None:
    health_snip = r'''
@app.get("/api/health")
def health():
    git_sha = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_SHA") or "unknown"
    release = os.getenv("RENDER_GIT_BRANCH") or os.getenv("RELEASE") or "unknown"
    return {"ok": True, "gitSha": git_sha, "release": release}
'''.lstrip("\n")
    # append near end
    t = t.rstrip() + "\n\n" + health_snip + "\n"

p.write_text(t, encoding="utf-8")
print("OK: patched app/main.py")
