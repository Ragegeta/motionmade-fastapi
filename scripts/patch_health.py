import re
from pathlib import Path

p = Path("app/main.py")
t = p.read_text(encoding="utf-8")

# Remove any existing /api/health route block (decorator + function)
t = re.sub(
    r'\n*@app\.get\(["\']/api/health["\']\)\n(?:@.*\n)*def\s+health\([^)]*\):\n(?:[ \t].*\n)+',
    "\n",
    t,
    flags=re.M,
)

# Append canonical /api/health at end
health = r'''
@app.get("/api/health")
def health():
    git_sha = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_SHA") or "unknown"
    release = os.getenv("RENDER_GIT_BRANCH") or os.getenv("RELEASE") or "unknown"
    return {"ok": True, "gitSha": git_sha, "release": release}
'''.lstrip("\n")

if '"/api/health"' not in t:
    t = t.rstrip() + "\n\n" + health + "\n"

p.write_text(t, encoding="utf-8")
print("OK: rewrote /api/health")
