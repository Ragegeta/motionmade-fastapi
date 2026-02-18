#!/usr/bin/env python3
"""Run autopilot pipeline: wipe -> discovery -> audit -> email-writing. Prints results of each step."""
import os
import sys
import json
import time

# Add parent so we can use requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

BASE_URL = os.environ.get("MM_PRODUCTION_URL", "https://motionmade-fastapi.onrender.com").rstrip("/")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
if not ADMIN_TOKEN:
    print("Set ADMIN_TOKEN env var (or pass as first arg)")
    sys.exit(1)

HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}", "Content-Type": "application/json"}


def main():
    if len(sys.argv) > 1:
        global ADMIN_TOKEN
        ADMIN_TOKEN = sys.argv[1].strip()
        HEADERS["Authorization"] = f"Bearer {ADMIN_TOKEN}"

    print("=== Production autopilot pipeline ===")
    print(f"Base URL: {BASE_URL}\n")

    # 1. Wipe
    print("--- Step 1: Wipe ---")
    r = requests.post(f"{BASE_URL}/api/leads/wipe", headers=HEADERS, timeout=60)
    if r.status_code != 200:
        print(f"Wipe failed: {r.status_code} {r.text}")
        sys.exit(1)
    data = r.json()
    print(json.dumps(data, indent=2))
    print(f"Wipe OK: deleted_leads={data.get('deleted_leads')}, deleted_logs={data.get('deleted_logs')}\n")
    time.sleep(1)

    # 2. Discovery (Bond Cleaning, Brisbane, target 10)
    print("--- Step 2: Discovery (Bond Cleaning, Brisbane, target 10) ---")
    r = requests.post(
        f"{BASE_URL}/api/leads/autopilot/discovery",
        headers=HEADERS,
        json={
            "trade_type": "Bond Cleaning",
            "suburb": "Brisbane",
            "city": "Brisbane",
            "target_count": 10,
        },
        timeout=180,
    )
    if r.status_code != 200:
        print(f"Discovery failed: {r.status_code} {r.text}")
        sys.exit(1)
    data = r.json()
    print(json.dumps(data, indent=2))
    print(f"Discovery OK: inserted={data.get('inserted')}, skipped_bad_website={data.get('skipped_bad_website')}\n")
    time.sleep(1)

    # List leads and verify websites (HEAD)
    print("--- Verify discovered leads (list + HEAD check) ---")
    r = requests.get(f"{BASE_URL}/api/leads", headers=HEADERS, timeout=30)
    if r.status_code != 200:
        print(f"List leads failed: {r.status_code} {r.text}")
    else:
        leads = r.json().get("leads") or []
        print(f"Total leads: {len(leads)}")
        import httpx
        for lead in leads:
            name = lead.get("business_name", "")
            website = (lead.get("website") or "").strip()
            email = lead.get("email") or ""
            status = lead.get("status", "")
            reachable = "N/A"
            if website:
                url = website if website.startswith(("http://", "https://")) else "https://" + website
                try:
                    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                        resp = client.head(url)
                        reachable = "yes" if resp.status_code == 200 else f"status={resp.status_code}"
                except Exception as e:
                    reachable = f"error: {e}"
            print(f"  - {name} | website={website or '(none)'} | email={email or '(none)'} | status={status} | HEAD={reachable}")
    print()
    time.sleep(1)

    # 3. Audit (all new)
    print("--- Step 3: Audit (all with status new) ---")
    r = requests.post(
        f"{BASE_URL}/api/leads/autopilot/audit",
        headers=HEADERS,
        json={},
        timeout=300,
    )
    if r.status_code != 200:
        print(f"Audit failed: {r.status_code} {r.text}")
        sys.exit(1)
    data = r.json()
    print(json.dumps(data, indent=2))
    print(f"Audit OK: audited={data.get('audited', 0)}\n")
    time.sleep(1)

    # 4. Email-writing (all audited/previewed)
    print("--- Step 4: Email-writing ---")
    r = requests.post(
        f"{BASE_URL}/api/leads/autopilot/email-writing",
        headers=HEADERS,
        json={},
        timeout=300,
    )
    if r.status_code != 200:
        print(f"Email-writing failed: {r.status_code} {r.text}")
        sys.exit(1)
    data = r.json()
    print(json.dumps(data, indent=2))
    print(f"Email-writing OK: written={data.get('written', 0)}\n")

    print("=== Pipeline complete ===")


if __name__ == "__main__":
    main()
