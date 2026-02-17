#!/usr/bin/env python3
"""Wipe, discovery Bond Cleaning Brisbane target 20, verify >=10 leads, audit, email-writing, check log for duplicates."""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

BASE_URL = os.environ.get("MM_PRODUCTION_URL", "https://motionmade-fastapi.onrender.com").rstrip("/")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}", "Content-Type": "application/json"}


def main():
    if not ADMIN_TOKEN:
        print("Set ADMIN_TOKEN")
        sys.exit(1)
    print("=== Discovery 20 + audit + email-writing + log check ===\n")

    # 1. Wipe
    print("--- 1. Wipe ---")
    r = requests.post(f"{BASE_URL}/api/leads/wipe", headers=HEADERS, timeout=60)
    r.raise_for_status()
    print(r.json())
    time.sleep(1)

    # 2. Discovery Bond Cleaning Brisbane target 20
    print("\n--- 2. Discovery (Bond Cleaning, Brisbane, target 20) ---")
    r = requests.post(
        f"{BASE_URL}/api/leads/autopilot/discovery",
        headers=HEADERS,
        json={"trade_type": "Bond Cleaning", "suburb": "", "city": "Brisbane", "target_count": 20},
        timeout=300,
    )
    r.raise_for_status()
    data = r.json()
    print(json.dumps(data, indent=2))
    inserted = data.get("inserted", 0)
    suburbs = data.get("suburbs_searched") or (data.get("suburb_searched") and [data["suburb_searched"]] or [])
    print(f"Suburbs searched: {len(suburbs)} -> {suburbs}")
    if inserted < 10:
        print(f"WARNING: expected >=10 leads, got {inserted}")
    else:
        print(f"OK: {inserted} leads (>=10)")
    time.sleep(1)

    # 3. Audit
    print("\n--- 3. Audit ---")
    r = requests.post(f"{BASE_URL}/api/leads/autopilot/audit", headers=HEADERS, json={}, timeout=180)
    r.raise_for_status()
    print(r.json())
    time.sleep(1)

    # 4. Email-writing (may 502 on Render if many leads)
    print("\n--- 4. Email-writing ---")
    try:
        r = requests.post(f"{BASE_URL}/api/leads/autopilot/email-writing", headers=HEADERS, json={}, timeout=180)
        r.raise_for_status()
        print(r.json())
    except Exception as e:
        print(f"Email-writing failed (may timeout): {e}")
    time.sleep(1)

    # 5. Fetch log and check for duplicate messages
    print("\n--- 5. Log duplicate check ---")
    r = requests.get(f"{BASE_URL}/api/leads/autopilot/log?limit=500", headers=HEADERS, timeout=30)
    r.raise_for_status()
    log = r.json().get("log") or []
    messages = [e.get("message") or "" for e in log]
    seen = set()
    dupes = []
    for m in messages:
        if m in seen:
            dupes.append(m)
        seen.add(m)
    if dupes:
        print(f"FAIL: {len(dupes)} duplicate log messages (sample): {dupes[:5]}")
    else:
        print(f"OK: no duplicate log messages ({len(messages)} entries)")
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
