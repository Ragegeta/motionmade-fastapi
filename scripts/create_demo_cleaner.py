#!/usr/bin/env python3
"""
Create demo_cleaner tenant with 10 cleaning FAQs for the landing page live demo.
Usage: ADMIN_TOKEN=xxx python scripts/create_demo_cleaner.py
       Or set ADMIN_TOKEN in .env. Server must be running.
"""
import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import requests

BASE_URL = os.environ.get("MM_TEST_BASE_URL", "http://localhost:8000").rstrip("/")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

FAQS = [
    {"question": "How much for a bond clean?", "answer": "Bond cleans start at $350 for a 2-bedroom and $450 for a 3-bedroom. Price depends on the condition. Contact us for an exact quote."},
    {"question": "Do you guarantee the bond back?", "answer": "Yes, 100% bond-back guarantee. If the agent isn't happy, we come back and fix it free within 72 hours."},
    {"question": "What's included in a bond clean?", "answer": "Full kitchen deep clean, all bathrooms, floors, windows inside, walls spot-clean, oven, rangehood, all fixtures. Carpet steam cleaning is $50 per room extra."},
    {"question": "Do you do Airbnb cleaning?", "answer": "Yes! Airbnb turnovers from $120. Linen changes, restocking, full clean between guests. Same-day turnovers available."},
    {"question": "What areas do you cover?", "answer": "Brisbane, Logan, Ipswich, Gold Coast. $30 travel surcharge outside Brisbane metro."},
    {"question": "How do I book?", "answer": "Call us on 0400 111 222, book on our website, or message us here. We need at least 48 hours notice for bond cleans."},
    {"question": "Do you bring your own supplies?", "answer": "Yes, all cleaning products and equipment included. Just make sure power and water are on."},
    {"question": "What payment do you accept?", "answer": "Cash, card, bank transfer, and Afterpay. Invoice emailed after the job."},
    {"question": "How much for a regular clean?", "answer": "Regular cleans from $150 for a 3-bedroom. Weekly, fortnightly, or one-off available."},
    {"question": "Are you insured?", "answer": "Fully insured with $20M public liability. ABN and insurance details on request."},
]


def main():
    if not ADMIN_TOKEN:
        print("Set ADMIN_TOKEN in environment or .env")
        sys.exit(1)
    headers = {"Authorization": f"Bearer {ADMIN_TOKEN}", "Content-Type": "application/json"}
    tenant_id = "demo_cleaner"
    name = "Brisbane Bond Cleaning"

    # Create tenant
    r = requests.post(
        f"{BASE_URL}/admin/api/tenants",
        headers=headers,
        json={"id": tenant_id, "name": name, "business_type": "Cleaner", "contact_phone": "0400 111 222"},
        timeout=30,
    )
    if r.status_code in (200, 201):
        print("Created tenant:", tenant_id)
    elif r.status_code == 400 and "already" in (r.json().get("detail") or "").lower():
        print("Tenant", tenant_id, "already exists, updating FAQs")
    else:
        print("Failed to create tenant:", r.status_code, r.text[:300])
        sys.exit(1)

    # Upload staged FAQs
    r = requests.put(
        f"{BASE_URL}/admin/api/tenant/{tenant_id}/faqs/staged",
        headers=headers,
        json=FAQS,
        timeout=60,
    )
    if not r.ok:
        print("Failed to upload FAQs:", r.status_code, r.text[:300])
        sys.exit(1)
    print("Uploaded", len(FAQS), "FAQs to staging")

    # Promote to live
    r = requests.post(
        f"{BASE_URL}/admin/api/tenant/{tenant_id}/promote",
        headers=headers,
        timeout=180,
    )
    if not r.ok:
        print("Failed to promote:", r.status_code, r.json().get("detail", r.text[:300]))
        sys.exit(1)
    print("Promoted to live")

    # Wait for embeddings
    print("Waiting 15s for embeddings...")
    time.sleep(15)

    # Verify suggested-questions
    r = requests.get(f"{BASE_URL}/api/v2/tenant/{tenant_id}/suggested-questions", timeout=10)
    if r.ok:
        data = r.json()
        qs = data.get("questions") or []
        print("Suggested questions count:", len(qs))
    else:
        print("Could not verify suggested-questions:", r.status_code)

    print("Done. Landing page demo tenant ready:", tenant_id)


if __name__ == "__main__":
    main()
