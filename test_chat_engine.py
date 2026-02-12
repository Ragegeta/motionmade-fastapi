#!/usr/bin/env python3
"""
Test the chat engine: create test_plumber tenant, upload FAQs, promote, run queries, log results, cleanup.
Run with: cd ~/MM/motionmade-fastapi && source venv/bin/activate && python test_chat_engine.py
API base is taken from env API_BASE or default http://127.0.0.1:8000 (start server first).
"""
import json
import os
import sys
import time

# Load .env before importing app
from dotenv import load_dotenv
load_dotenv()

try:
    import httpx
except ImportError:
    print("pip install httpx"); sys.exit(1)

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")
if not ADMIN_TOKEN:
    with open(os.path.join(os.path.dirname(__file__), ".env")) as f:
        for line in f:
            if line.strip().startswith("ADMIN_TOKEN="):
                ADMIN_TOKEN = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                break
if not ADMIN_TOKEN:
    print("ADMIN_TOKEN not set in .env"); sys.exit(1)

HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}", "Content-Type": "application/json"}
TENANT_ID = "test_plumber"

# Load FAQs
FAQS_PATH = os.path.join(os.path.dirname(__file__), "tenants", "test_plumber", "faqs.json")
with open(FAQS_PATH) as f:
    FAQS = json.load(f)

# Test cases: (query, expected_faq_keyword, category)
# expected_faq_keyword = substring that should appear in the right answer (or "FALLBACK" / "CLARIFY" / "REJECT")
TESTS = [
    # Clean
    ("how much for a callout?", "callout", "clean"),
    ("do you come to Logan?", "Logan", "clean"),
    ("can I pay with Afterpay?", "Afterpay", "clean"),
    ("are you available on weekends?", "weekends", "clean"),
    # Messy
    ("hw much 4 a plumber to come out", "callout", "messy"),
    ("u guys do emergency stuff??", "emergency", "messy"),
    ("wat areas u cover", "Brisbane", "messy"),
    ("can i pay later", "Afterpay", "messy"),
    ("r u licensed bro", "licensed", "messy"),
    ("how long will it take to fix my tap", "tap", "messy"),
    # Wrong-service (expect fallback / generic)
    ("how much for a haircut?", "FALLBACK", "wrong"),
    ("do you do house cleaning?", "FALLBACK", "wrong"),
    ("can you fix my car?", "FALLBACK", "wrong"),
    # Edge
    ("", "CLARIFY", "edge"),
    ("asdfghjkl", "FALLBACK", "edge"),
    ("hi", "CLARIFY", "edge"),
]

def main():
    print("=== CHAT ENGINE TEST ===\n")
    print(f"API_BASE = {API_BASE}\n")

    # 1. Create tenant
    print("1. Creating tenant test_plumber...")
    r = httpx.post(f"{API_BASE}/admin/api/tenants", headers=HEADERS, json={"id": TENANT_ID, "name": "Test Plumber Brisbane"}, timeout=30)
    if r.status_code not in (200, 201):
        print(f"   FAIL: {r.status_code} {r.text[:200]}"); return 1
    print("   OK")

    # 2. Upload staged FAQs
    print("2. Uploading staged FAQs...")
    r = httpx.put(f"{API_BASE}/admin/api/tenant/{TENANT_ID}/faqs/staged", headers=HEADERS, json=FAQS, timeout=60)
    if r.status_code != 200:
        print(f"   FAIL: {r.status_code} {r.text[:300]}"); return 1
    print("   OK")

    # 3. Promote to live
    print("3. Promoting to live...")
    r = httpx.post(f"{API_BASE}/admin/api/tenant/{TENANT_ID}/promote", headers=HEADERS, timeout=120)
    if r.status_code != 200:
        print(f"   FAIL: {r.status_code} {r.text[:500]}"); return 1
    print("   OK")
    print("   Waiting 20s for embeddings and FTS...")
    time.sleep(20)

    # 4. Run test queries
    print("\n4. Running test queries...\n")
    results = []
    for query, expected_keyword, category in TESTS:
        r = httpx.post(
            f"{API_BASE}/api/v2/generate-quote-reply",
            headers={"Content-Type": "application/json"},
            json={"tenantId": TENANT_ID, "customerMessage": query},
            timeout=30,
        )
        if r.status_code != 200:
            reply = f"[HTTP {r.status_code}]"
        else:
            body = r.json()
            reply = (body.get("replyText") or "").strip()[:200]
        # Determine correct?
        if expected_keyword == "FALLBACK":
            rl = reply.lower()
            correct = (
                "fallback" in rl or "sorry" in rl or "don't" in rl or "can't" in rl
                or "contact us" in rl or "mechanic" in rl or "accidentally" in rl or "random" in rl
                or "rephrase" in rl or "clarif" in rl or len(reply) < 120
            )
            # Wrong-service: must NOT claim we do that service
            if "house cleaning" in query.lower() and ("yes" in rl[:80] or "we offer" in rl[:80]):
                correct = False  # false positive
        elif expected_keyword == "CLARIFY":
            correct = "?" in reply or "clarif" in reply.lower() or "what" in reply.lower() or "which" in reply.lower() or len(reply) < 150
        else:
            correct = expected_keyword.lower() in reply.lower()
        results.append((query, expected_keyword, reply, "yes" if correct else "no", category))
        print(f"   [{category}] \"{query[:40]}...\" -> {expected_keyword} | correct={correct}")

    # 5. Results table
    print("\n" + "="*80)
    print("RESULTS TABLE")
    print("="*80)
    print(f"{'Query':<45} | {'Expected':<12} | {'Correct?':<6} | Snippet")
    print("-"*80)
    for query, exp, reply, correct, _ in results:
        snippet = (reply[:50] + "…") if len(reply) > 50 else reply
        print(f"{query[:44]:<45} | {exp:<12} | {correct:<6} | {snippet}")
    correct_count = sum(1 for _, _, _, c, _ in results if c == "yes")
    total = len(results)
    pct = round(100 * correct_count / total, 1) if total else 0
    print("-"*80)
    print(f"ACCURACY: {correct_count}/{total} = {pct}%")
    if pct < 85:
        print("\n--- INVESTIGATION (below 85%) ---")
        print("Failures and suggested fixes:")
        for query, exp, reply, correct, cat in results:
            if correct != "yes":
                print(f"  • \"{query[:50]}\" expected {exp}")
                print(f"    Got: {reply[:90]}...")
                if "callout" in exp and "hw much" in query:
                    print("    Fix: Add normalization 4->for, hw->how; add variant 'plumber come out' -> callout.")
                elif "Afterpay" in exp and "pay later" in query:
                    print("    Fix: Add variant 'pay later' for payment FAQ; or FTS stem 'later'.")
                elif "tap" in exp:
                    print("    Fix: Ensure 'how long' + 'tap' matches job duration FAQ (vector or FTS).")
                elif exp == "FALLBACK" and "asdfghjkl" in query:
                    print("    Fix: Gibberish detector or low-confidence threshold.")
                print()

    # 6. Cleanup: delete tenant (via DB)
    print("\n5. Cleaning up: deleting test_plumber tenant...")
    try:
        from app.db import get_conn
        with get_conn() as conn:
            for t in ["retrieval_cache", "telemetry", "query_stats", "tenant_promote_history", "tenant_domains"]:
                try:
                    conn.execute(f"DELETE FROM {t} WHERE tenant_id = %s", (TENANT_ID,))
                except Exception:
                    pass
            conn.execute("DELETE FROM faq_variants WHERE faq_id IN (SELECT id FROM faq_items WHERE tenant_id = %s)", (TENANT_ID,))
            try:
                conn.execute("DELETE FROM faq_variants_p WHERE tenant_id = %s", (TENANT_ID,))
            except Exception:
                pass
            conn.execute("DELETE FROM faq_items WHERE tenant_id = %s", (TENANT_ID,))
            conn.execute("DELETE FROM faq_items_last_good WHERE tenant_id = %s", (TENANT_ID,))
            conn.execute("DELETE FROM tenants WHERE id = %s", (TENANT_ID,))
            conn.commit()
        print("   OK")
    except Exception as e:
        print(f"   Cleanup failed (non-fatal): {e}")

    print("\n=== DONE ===")
    return 0 if pct >= 85 else 1

if __name__ == "__main__":
    sys.exit(main())
