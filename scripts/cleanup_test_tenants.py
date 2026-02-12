#!/usr/bin/env python3
"""
Delete all tenants that are NOT in the keep list.
Usage: ADMIN_TOKEN=xxx python scripts/cleanup_test_tenants.py
       Or set ADMIN_TOKEN in .env (script loads dotenv).
"""
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import requests

BASE_URL = os.environ.get("MM_TEST_BASE_URL", "http://localhost:8000").rstrip("/")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
KEEP = {"sparkys_electrical", "brissy_cleaners", "motionmade_demo"}


def main():
    if not ADMIN_TOKEN:
        print("Set ADMIN_TOKEN in environment or .env")
        sys.exit(1)
    headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
    r = requests.get(f"{BASE_URL}/admin/api/tenants", headers=headers, timeout=30)
    if not r.ok:
        print("Failed to list tenants:", r.status_code, r.text[:200])
        sys.exit(1)
    data = r.json()
    tenants = data.get("tenants") or []
    to_delete = [t["id"] for t in tenants if t["id"] not in KEEP]
    if not to_delete:
        print("No test tenants to delete. Kept:", sorted(KEEP))
        return
    print("Deleting:", to_delete)
    for tid in to_delete:
        dr = requests.delete(f"{BASE_URL}/admin/api/tenant/{tid}", headers=headers, timeout=30)
        if dr.ok:
            print("  Deleted:", tid)
        else:
            print("  Failed to delete", tid, dr.status_code)
    print("Done. Remaining tenants should be:", sorted(KEEP))


if __name__ == "__main__":
    main()
