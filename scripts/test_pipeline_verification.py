#!/usr/bin/env python3
"""Verify: wipe, discovery x2 (no duplicate leads), audit, email-writing, send-ready x2 (second returns Already sending)."""
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
    if len(sys.argv) > 1:
        global ADMIN_TOKEN, HEADERS
        ADMIN_TOKEN = sys.argv[1].strip()
        HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}", "Content-Type": "application/json"}
    if not ADMIN_TOKEN:
        print("Set ADMIN_TOKEN")
        sys.exit(1)

    print("=== Pipeline verification ===\n")
    results = {}

    # 1. Wipe
    print("--- 1. Wipe ---")
    r = requests.post(f"{BASE_URL}/api/leads/wipe", headers=HEADERS, timeout=60)
    r.raise_for_status()
    data = r.json()
    results["wipe"] = data
    print(json.dumps(data, indent=2))
    print()
    time.sleep(1)

    # 2. Discovery run 1 (Bond Cleaning, Brisbane, All suburbs)
    print("--- 2. Discovery #1 (Bond Cleaning, Brisbane, suburb=All) ---")
    r = requests.post(
        f"{BASE_URL}/api/leads/autopilot/discovery",
        headers=HEADERS,
        json={"trade_type": "Bond Cleaning", "suburb": "", "city": "Brisbane", "target_count": 5},
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    results["discovery1"] = data
    print(json.dumps(data, indent=2))
    print(f"inserted={data.get('inserted')}, suburb_searched={data.get('suburb_searched')}\n")
    time.sleep(1)

    # 3. Discovery run 2 (should pick different suburb when All)
    print("--- 3. Discovery #2 (Bond Cleaning, Brisbane, suburb=All) ---")
    r = requests.post(
        f"{BASE_URL}/api/leads/autopilot/discovery",
        headers=HEADERS,
        json={"trade_type": "Bond Cleaning", "suburb": "", "city": "Brisbane", "target_count": 5},
        timeout=180,
    )
    r.raise_for_status()
    data = r.json()
    results["discovery2"] = data
    print(json.dumps(data, indent=2))
    print(f"inserted={data.get('inserted')}, suburb_searched={data.get('suburb_searched')}\n")
    time.sleep(1)

    # 4. Verify no duplicate leads (by business_name)
    print("--- 4. Verify no duplicate leads ---")
    r = requests.get(f"{BASE_URL}/api/leads", headers=HEADERS, timeout=30)
    r.raise_for_status()
    leads = r.json().get("leads") or []
    names = [str((l.get("business_name") or "").strip()).lower() for l in leads]
    unique_names = set(n for n in names if n)
    duplicate_count = len(names) - len(unique_names)
    results["leads_total"] = len(leads)
    results["leads_unique_names"] = len(unique_names)
    results["duplicate_names"] = duplicate_count
    print(f"Total leads: {len(leads)}, Unique business names: {len(unique_names)}, Duplicates: {duplicate_count}")
    if duplicate_count > 0:
        print("FAIL: duplicate business names found")
    else:
        print("OK: no duplicate leads\n")
    time.sleep(1)

    # 5. Audit (may 502 on Render if many leads)
    print("--- 5. Audit ---")
    try:
        r = requests.post(f"{BASE_URL}/api/leads/autopilot/audit", headers=HEADERS, json={}, timeout=120)
        r.raise_for_status()
        data = r.json()
        results["audit"] = data
        print(json.dumps(data, indent=2))
    except Exception as e:
        results["audit"] = {"error": str(e)}
        print(f"Audit failed (may timeout on Render): {e}")
    print()
    time.sleep(1)

    # 6. Email-writing
    print("--- 6. Email-writing ---")
    try:
        r = requests.post(f"{BASE_URL}/api/leads/autopilot/email-writing", headers=HEADERS, json={}, timeout=120)
        r.raise_for_status()
        data = r.json()
        results["email_writing"] = data
        print(json.dumps(data, indent=2))
    except Exception as e:
        results["email_writing"] = {"error": str(e)}
        print(f"Email-writing failed: {e}")
    print()
    time.sleep(1)

    # 7. Send-ready twice rapidly: second should return "Already sending" when first has work to do
    print("--- 7. Send-ready x2 (second should be Already sending if first has leads) ---")
    r1 = requests.post(f"{BASE_URL}/api/leads/autopilot/send-ready", headers=HEADERS, timeout=15)
    data1 = r1.json()
    results["send_ready_1"] = data1
    print("First call:", json.dumps(data1))
    r2 = requests.post(f"{BASE_URL}/api/leads/autopilot/send-ready", headers=HEADERS, timeout=15)
    data2 = r2.json()
    results["send_ready_2"] = data2
    print("Second call:", json.dumps(data2))
    to_send = data1.get("to_send") or 0
    if to_send > 0:
        if not data2.get("ok") and "Already sending" in (data2.get("message") or ""):
            print("OK: second call returned Already sending\n")
        else:
            print("FAIL: second call should return ok:false, message: Already sending\n")
    else:
        print("(No ready leads to send; second call may return Sending started with to_send=0)\n")

    print("=== All results ===")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
