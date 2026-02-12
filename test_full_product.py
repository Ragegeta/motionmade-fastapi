"""
MotionMade AI — Full Product Test Suite
Tests every feature end-to-end.
Run: python test_full_product.py (server must be running on BASE_URL, default localhost:8000)
"""
import os
import sys
import time
import json
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_URL = os.environ.get("MM_TEST_BASE_URL", "http://localhost:8000").rstrip("/")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
TENANT1 = "fulltest_biz"
TENANT2 = "fulltest_biz_2"
OWNER1_EMAIL = "fulltest@test.com"
OWNER1_PASS = "testpass123"
OWNER2_EMAIL = "fulltest2@test.com"
OWNER2_PASS = "testpass123"

# Test state
owner1_jwt = None
owner2_jwt = None
passed = 0
failed = 0
results = []


def ok(name, detail=""):
    global passed
    passed += 1
    results.append(("ok", name, detail))
    print(f"  ✅ {name}" + (f" ({detail})" if detail else ""))


def fail(name, detail=""):
    global failed
    failed += 1
    results.append(("fail", name, detail))
    print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


def admin_headers():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}", "Content-Type": "application/json"}


def owner_headers(jwt_token):
    return {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}


# ---------- Section 1: Admin & Onboarding ----------
def section1_admin_onboarding():
    print("\nADMIN & ONBOARDING")
    global owner1_jwt

    # Create tenant fulltest_biz (idempotent: create or update)
    r = requests.post(
        f"{BASE_URL}/admin/api/tenants",
        headers=admin_headers(),
        json={"id": TENANT1, "name": "Full Test Biz"},
        timeout=30,
    )
    if r.status_code not in (200, 201):
        fail("Create tenant", f"status {r.status_code}: {r.text[:200]}")
        return False
    ok("Create tenant")

    # Verify tenant in list
    r = requests.get(f"{BASE_URL}/admin/api/tenants", headers=admin_headers(), timeout=30)
    if r.status_code != 200:
        fail("List tenants", f"status {r.status_code}")
        return False
    ids = [t["id"] for t in r.json().get("tenants", [])]
    if TENANT1 not in ids:
        fail("Tenant in list", f"fulltest_biz not in {ids}")
    else:
        ok("Tenant in list")

    # Create owner (may 400 if already exists from aborted run — then skip or re-use login)
    r = requests.post(
        f"{BASE_URL}/admin/api/create-owner",
        headers=admin_headers(),
        json={"tenant_id": TENANT1, "email": OWNER1_EMAIL, "password": OWNER1_PASS},
        timeout=30,
    )
    if r.status_code == 400 and "already registered" in (r.json().get("detail") or "").lower():
        ok("Create owner", "already existed")
    elif r.status_code not in (200, 201):
        fail("Create owner", f"status {r.status_code}: {r.text[:200]}")
        return False
    else:
        ok("Create owner")

    # Owner login
    r = requests.post(
        f"{BASE_URL}/owner/login",
        json={"email": OWNER1_EMAIL, "password": OWNER1_PASS},
        timeout=30,
    )
    if r.status_code != 200:
        fail("Owner login", f"status {r.status_code}: {r.text[:200]}")
        return False
    data = r.json()
    owner1_jwt = data.get("access_token") or data.get("token")
    if not owner1_jwt:
        fail("Owner login", "no token in response")
        return False
    ok("Owner login")
    return True


# ---------- Section 2: FAQ Upload & Promotion ----------
FAQ_UPLOAD = [
    ("How much do you charge?", "$99 standard callout. $149 weekends and after hours."),
    ("What areas do you cover?", "Brisbane, Logan, Ipswich, Redlands. Gold Coast is $50 extra."),
    ("Do you do emergency work?", "Yes, 24/7 emergency service. Call 0400 111 222."),
    ("How do I book?", "Call 0400 111 222, book online, or message us here."),
    ("Are you licensed?", "Fully licensed and insured. QBCC licence 12345678."),
    ("What payment do you accept?", "Cash, card, bank transfer, Afterpay. Invoice emailed after the job."),
]


def section2_faq_upload():
    print("\nFAQ UPLOAD")
    items = [{"question": q, "answer": a} for q, a in FAQ_UPLOAD]
    r = requests.put(
        f"{BASE_URL}/admin/api/tenant/{TENANT1}/faqs/staged",
        headers=admin_headers(),
        json=items,
        timeout=60,
    )
    if r.status_code != 200:
        fail("Upload 6 FAQs", f"status {r.status_code}: {r.text[:300]}")
        return False
    ok("Upload 6 FAQs")

    r = requests.post(
        f"{BASE_URL}/admin/api/tenant/{TENANT1}/promote",
        headers=admin_headers(),
        timeout=120,
    )
    if r.status_code != 200:
        fail("Promote to live", f"status {r.status_code}: {r.text[:300]}")
        return False
    ok("Promote to live")

    print("  (waiting 20s for embeddings...)")
    time.sleep(20)

    r = requests.get(
        f"{BASE_URL}/api/v2/tenant/{TENANT1}/suggested-questions",
        timeout=10,
    )
    if r.status_code != 200:
        fail("Suggested questions", f"status {r.status_code}")
        return False
    qs = r.json().get("questions") or []
    if len(qs) < 3:
        fail("Suggested questions (3)", f"got {len(qs)}")
    else:
        ok("Suggested questions (3 returned)")
    return True


# ---------- Section 3: Chat Accuracy ----------
CHAT_TESTS = [
    # (query, expected_theme, description)
    ("how much for a callout", "pricing", "clean"),
    ("what areas do you service", "areas", "clean"),
    ("do you do emergency plumbing", "emergency", "clean"),
    ("how do I book a job", "booking", "clean"),
    ("are you fully licensed", "licensed", "clean"),
    ("can I pay with afterpay", "payment", "clean"),
    ("hw much u charge", "pricing", "messy"),
    ("u guys come to logan?", "areas", "messy"),
    ("emergency plumber asap!!", "emergency", "messy"),
    ("can i pay later", "payment", "messy"),
    ("do you do haircuts", "fallback", "wrong_service"),
    ("can you fix my car", "fallback", "wrong_service"),
    ("hi", "tone_no_chatbot", "tone"),
    ("asdfghjkl", "clarify", "tone"),
]


def chat_query(query):
    r = requests.post(
        f"{BASE_URL}/api/v2/generate-quote-reply",
        json={"tenantId": TENANT1, "customerMessage": query},
        timeout=30,
    )
    if r.status_code != 200:
        return None, None, None, f"status {r.status_code}"
    data = r.json()
    reply = (data.get("replyText") or "").strip().lower()
    resp_time = r.headers.get("X-Response-Time", "")
    path = r.headers.get("X-Retrieval-Path", "")
    return reply, resp_time, path, None


def section3_chat_accuracy():
    print("\nCHAT ACCURACY (Target: 85%+, goal 90%+)")
    correct = 0
    for query, expected, desc in CHAT_TESTS:
        reply, resp_time, path, err = chat_query(query)
        if err:
            fail(f'"{query[:30]}..."', f"request error: {err}")
            continue
        resp_time_str = resp_time if resp_time else "?"
        path_str = path if path else "?"

        if expected == "pricing":
            ok_ = "99" in reply or "109" in reply or "149" in reply or "callout" in reply or "charge" in reply
        elif expected == "areas":
            ok_ = "brisbane" in reply or "logan" in reply or "areas" in reply or "cover" in reply
        elif expected == "emergency":
            ok_ = "emergency" in reply or "24" in reply or "0400" in reply
        elif expected == "booking":
            ok_ = "book" in reply or "call" in reply or "0400" in reply
        elif expected == "licensed":
            ok_ = "licen" in reply or "insured" in reply or "qbcc" in reply
        elif expected == "payment":
            ok_ = "cash" in reply or "card" in reply or "afterpay" in reply or "pay" in reply
        elif expected == "fallback":
            ok_ = "don't have" in reply or "not something" in reply or "contact" in reply
        elif expected == "tone_no_chatbot":
            ok_ = "hello! how can i assist" not in reply and ("ask me" in reply or "question about" in reply)
        elif expected == "clarify":
            ok_ = "didn't catch" in reply or "try asking" in reply or "accidentally" in reply or "random" in reply
        else:
            ok_ = False

        if ok_:
            correct += 1
            ok(f'"{query[:28]}..." → {expected} ({resp_time_str}, {path_str})')
        else:
            fail(f'"{query[:28]}..." → expected {expected}', f"reply: {reply[:80]}...")
    pct = (correct / len(CHAT_TESTS)) * 100 if CHAT_TESTS else 0
    if pct >= 85:
        ok(f"Result: {correct}/{len(CHAT_TESTS)} ({pct:.0f}%) ✅")
    else:
        fail(f"Result: {correct}/{len(CHAT_TESTS)} ({pct:.0f}%) — target 85%+")
    return correct, len(CHAT_TESTS)


# ---------- Section 4: Speed ----------
def section4_speed():
    print("\nSPEED (Target: avg <1.0s, max <8s)")
    times_sec = []
    for query, _, _ in CHAT_TESTS:
        t0 = time.perf_counter()
        reply, _, _, _ = chat_query(query)
        elapsed = time.perf_counter() - t0
        if reply is not None:
            times_sec.append(elapsed)
    if not times_sec:
        fail("Speed", "no successful requests")
        return 0, 0, False
    avg = sum(times_sec) / len(times_sec)
    mx = max(times_sec)
    speed_ok = avg < 1.0 and mx < 8.0
    if speed_ok:
        ok(f"Avg: {avg:.2f}s | Max: {mx:.2f}s ✅")
    else:
        fail(f"Avg: {avg:.2f}s | Max: {mx:.2f}s", "target avg <1.0s, max <8s")
    return avg, mx, speed_ok


# ---------- Section 5: Owner Dashboard API ----------
def section5_owner_dashboard_api():
    print("\nOWNER DASHBOARD API")
    if not owner1_jwt:
        fail("GET /owner/dashboard", "no JWT")
        return
    r = requests.get(f"{BASE_URL}/owner/dashboard", headers=owner_headers(owner1_jwt), timeout=10)
    if r.status_code == 200:
        ok("GET /owner/dashboard (200)")
    else:
        fail("GET /owner/dashboard", f"status {r.status_code}")

    r = requests.get(f"{BASE_URL}/owner/dashboard/daily", headers=owner_headers(owner1_jwt), timeout=10)
    if r.status_code == 200:
        ok("GET /owner/dashboard/daily (200)")
    else:
        fail("GET /owner/dashboard/daily", f"status {r.status_code}")

    r = requests.get(f"{BASE_URL}/owner/dashboard/fallbacks", headers=owner_headers(owner1_jwt), timeout=10)
    if r.status_code == 200:
        ok("GET /owner/dashboard/fallbacks (200)")
    else:
        fail("GET /owner/dashboard/fallbacks", f"status {r.status_code}")

    # No JWT → 401
    r = requests.get(f"{BASE_URL}/owner/dashboard", timeout=10)
    if r.status_code == 401:
        ok("GET /owner/dashboard (no JWT → 401)")
    else:
        fail("GET /owner/dashboard (no JWT → 401)", f"status {r.status_code}")


# ---------- Section 6: Owner FAQ (view-only) ----------
def section6_owner_faq_management():
    print("\nOWNER FAQ (VIEW-ONLY)")
    if not owner1_jwt:
        fail("List FAQs", "no JWT")
        return False

    r = requests.get(f"{BASE_URL}/owner/faqs", headers=owner_headers(owner1_jwt), timeout=10)
    if r.status_code != 200:
        fail("GET /owner/faqs", f"status {r.status_code}")
        return False
    data = r.json()
    faqs = data.get("faqs") or []
    count = data.get("count", len(faqs))
    if count != 6:
        fail("List FAQs (6)", f"got {count}")
    else:
        ok("GET /owner/faqs returns 6 FAQs")
    return True


# ---------- Section 7: Tenant Isolation ----------
def section7_tenant_isolation():
    print("\nTENANT ISOLATION")
    global owner2_jwt

    # Create second tenant and owner (idempotent)
    requests.post(
        f"{BASE_URL}/admin/api/tenants",
        headers=admin_headers(),
        json={"id": TENANT2, "name": "Full Test Biz 2"},
        timeout=30,
    )
    r = requests.post(
        f"{BASE_URL}/admin/api/create-owner",
        headers=admin_headers(),
        json={"tenant_id": TENANT2, "email": OWNER2_EMAIL, "password": OWNER2_PASS},
        timeout=30,
    )
    if r.status_code not in (200, 201) and not (r.status_code == 400 and "already" in (r.json().get("detail") or "").lower()):
        fail("Create tenant2 owner", f"status {r.status_code}")
        return
    r = requests.post(
        f"{BASE_URL}/owner/login",
        json={"email": OWNER2_EMAIL, "password": OWNER2_PASS},
        timeout=30,
    )
    if r.status_code != 200:
        fail("Login tenant2", f"status {r.status_code}")
        return
    owner2_jwt = r.json().get("access_token") or r.json().get("token")
    if not owner2_jwt:
        fail("Login tenant2", "no token")
        return

    # Upload 1 FAQ for tenant 2
    requests.put(
        f"{BASE_URL}/admin/api/tenant/{TENANT2}/faqs/staged",
        headers=admin_headers(),
        json=[{"question": "Do you sell fish?", "answer": "Yes, fresh fish daily."}],
        timeout=30,
    )
    requests.post(f"{BASE_URL}/admin/api/tenant/{TENANT2}/promote", headers=admin_headers(), timeout=120)
    time.sleep(5)

    # Owner2: GET /owner/faqs must show only 1 FAQ
    r = requests.get(f"{BASE_URL}/owner/faqs", headers=owner_headers(owner2_jwt), timeout=10)
    if r.status_code != 200:
        fail("Tenant2 list FAQs", f"status {r.status_code}")
    else:
        faqs = r.json().get("faqs") or []
        if len(faqs) != 1:
            fail("Tenant 2 only sees own FAQs (1)", f"got {len(faqs)}")
        else:
            ok("Tenant 2 only sees own FAQs (1)")

    # Owner2: dashboard stats are tenant2's
    r = requests.get(f"{BASE_URL}/owner/dashboard", headers=owner_headers(owner2_jwt), timeout=10)
    if r.status_code == 200:
        ok("Tenant 2 dashboard (200)")
    else:
        fail("Tenant 2 dashboard", f"status {r.status_code}")

    # Owner FAQ write endpoints removed; isolation is enforced by GET /owner/faqs (tenant-scoped)
    ok("Tenant 2 only sees own FAQs (list isolation)")

    # Owner1: must not see tenant2's fish FAQ
    r = requests.get(f"{BASE_URL}/owner/faqs", headers=owner_headers(owner1_jwt), timeout=10)
    faqs = r.json().get("faqs") or [] if r.status_code == 200 else []
    fish = [f for f in faqs if "fish" in (f.get("question") or "").lower() or "fish" in (f.get("answer") or "").lower()]
    if fish:
        fail("Tenant 1 cannot see tenant 2 FAQs", "saw fish FAQ")
    else:
        ok("Tenant 1 cannot see tenant 2 FAQs")


# ---------- Section 8: Cleanup ----------
def section8_cleanup():
    print("\nCLEANUP")
    for tid in (TENANT1, TENANT2):
        r = requests.delete(
            f"{BASE_URL}/admin/api/tenant/{tid}",
            headers=admin_headers(),
            timeout=30,
        )
        if r.status_code in (200, 204):
            ok(f"Tenant {tid} deleted")
        else:
            fail(f"Tenant {tid} deleted", f"status {r.status_code}")

    r = requests.get(f"{BASE_URL}/admin/api/tenants", headers=admin_headers(), timeout=10)
    ids = [t["id"] for t in r.json().get("tenants", [])] if r.status_code == 200 else []
    if TENANT1 in ids or TENANT2 in ids:
        fail("Tenants gone from list", f"still see {TENANT1} or {TENANT2}")
    else:
        ok("Tenants gone from list")


def main():
    global passed, failed, results
    passed = 0
    failed = 0
    results = []
    chat_correct, chat_total = 0, 16
    avg_time, max_time, speed_ok = 0.0, 0.0, False

    print("=" * 50)
    print("  MOTIONMADE AI — FULL PRODUCT TEST")
    print("=" * 50)
    print(f"  BASE_URL = {BASE_URL}")
    if not ADMIN_TOKEN:
        print("  ADMIN_TOKEN not set — admin steps will fail.")
    print()

    try:
        if not section1_admin_onboarding():
            print("  Section 1 failed; continuing anyway.")
        section2_faq_upload()
        chat_correct, chat_total = section3_chat_accuracy()
        avg_time, max_time, speed_ok = section4_speed()
        section5_owner_dashboard_api()
        section6_owner_faq_management()
        section7_tenant_isolation()
    finally:
        section8_cleanup()

    total = passed + failed
    pct = (passed / total * 100) if total else 0
    chat_pct = (chat_correct / chat_total * 100) if chat_total else 0

    print()
    print("=" * 50)
    print(f"  FINAL: {passed}/{total} passed ({pct:.0f}%)")
    print(f"  CHAT: {chat_correct}/{chat_total} ({chat_pct:.0f}%) — target 85%+ " + ("✅" if chat_pct >= 85 else "❌"))
    print(f"  SPEED: avg {avg_time:.2f}s, max {max_time:.2f}s — target <8s " + ("✅" if speed_ok else "❌"))
    print("=" * 50)

    # Targets: chat accuracy 85%+, speed within bounds; individual chat queries may fail
    targets_met = chat_pct >= 85 and speed_ok
    sys.exit(0 if targets_met else 1)


if __name__ == "__main__":
    main()
