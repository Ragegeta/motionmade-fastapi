#!/usr/bin/env python3
"""
Speed benchmark for the chat retrieval pipeline.
Sends 20 queries to the local server, measures response time, prints table and summary.
FAILS if any query > 2.5s or accuracy < 85%.

Self-contained: creates test_plumber, uploads FAQs, promotes, then runs 20 queries.
Start the server first (e.g. uvicorn app.main:app --reload).
"""
import json
import os
import sys
import time

from dotenv import load_dotenv
load_dotenv()

try:
    import httpx
except ImportError:
    print("pip install httpx")
    sys.exit(1)

API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")
if not ADMIN_TOKEN:
    try:
        with open(os.path.join(os.path.dirname(__file__), ".env")) as f:
            for line in f:
                if line.strip().startswith("ADMIN_TOKEN="):
                    ADMIN_TOKEN = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                    break
    except Exception:
        pass
if not ADMIN_TOKEN:
    print("ADMIN_TOKEN not set in .env")
    sys.exit(1)
ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_TOKEN}", "Content-Type": "application/json"}

# Use test_plumber (must run test_chat_engine.py first to load FAQs)
BENCHMARK_TENANT = "test_plumber"

BENCHMARK_QUERIES = [
    # (tenant_id, query) — Fast path (should match easily, < 1.5s)
    (BENCHMARK_TENANT, "how much for a callout"),
    (BENCHMARK_TENANT, "do you do emergency work"),
    (BENCHMARK_TENANT, "what areas do you cover"),
    (BENCHMARK_TENANT, "are you licensed"),
    (BENCHMARK_TENANT, "how do I book"),
    # Messy text (may trigger rewriter, < 2.0s) — plumber wording for test_plumber
    (BENCHMARK_TENANT, "hw much 4 a plumber to come out"),
    (BENCHMARK_TENANT, "u guys do emergency stuff??"),
    (BENCHMARK_TENANT, "wat areas u cover"),
    (BENCHMARK_TENANT, "can i pay later"),
    (BENCHMARK_TENANT, "r u licensed bro"),
    # Wrong service (should fallback quickly, < 2.0s)
    (BENCHMARK_TENANT, "how much for a haircut"),
    (BENCHMARK_TENANT, "do you do house cleaning"),
    # Edge cases
    (BENCHMARK_TENANT, ""),
    (BENCHMARK_TENANT, "hi"),
    (BENCHMARK_TENANT, "asdfghjkl"),
    # Extra to reach 20
    (BENCHMARK_TENANT, "do you work saturdays"),
    (BENCHMARK_TENANT, "wats ur callout fee"),
    (BENCHMARK_TENANT, "do you do solar panels"),
    (BENCHMARK_TENANT, "smoke alarm beeping"),
    (BENCHMARK_TENANT, "powerpoint not working"),
]

# Expected: True = should get FAQ hit, False = should get fallback/clarify
# test_plumber: electrical queries (smoke alarm, powerpoint) = wrong service = FALL
EXPECTED_HIT = [
    True, True, True, True, True,   # fast path
    True, True, True, True, True,   # messy
    False, False,                   # wrong service (haircut, house cleaning)
    False, False, False,            # edge (empty, hi, gibberish)
    True, True,                     # weekends, callout fee
    False,                          # solar
    False, False,                   # smoke alarm, powerpoint (wrong for plumber)
]


def main():
    print("=== SPEED BENCHMARK ===\n")
    print(f"API_BASE = {API_BASE}\n")

    # Setup: create tenant, upload FAQs, promote (so we have data to query)
    print("Setup: creating test_plumber and loading FAQs...")
    r = httpx.post(f"{API_BASE}/admin/api/tenants", headers=ADMIN_HEADERS, json={"id": BENCHMARK_TENANT, "name": "Test Plumber Brisbane"}, timeout=30)
    if r.status_code not in (200, 201):
        print(f"   Create tenant: {r.status_code} {r.text[:200]}")
        sys.exit(1)
    faqs_path = os.path.join(os.path.dirname(__file__), "tenants", "test_plumber", "faqs.json")
    with open(faqs_path) as f:
        faqs = json.load(f)
    r = httpx.put(f"{API_BASE}/admin/api/tenant/{BENCHMARK_TENANT}/faqs/staged", headers=ADMIN_HEADERS, json=faqs, timeout=60)
    if r.status_code != 200:
        print(f"   Upload FAQs: {r.status_code}")
        sys.exit(1)
    r = httpx.post(f"{API_BASE}/admin/api/tenant/{BENCHMARK_TENANT}/promote", headers=ADMIN_HEADERS, timeout=120)
    if r.status_code != 200:
        print(f"   Promote: {r.status_code} {r.text[:300]}")
        sys.exit(1)
    print("   Waiting 15s for embeddings...")
    time.sleep(15)
    print()

    results = []
    for i, (tenant_id, query) in enumerate(BENCHMARK_QUERIES):
        t0 = time.perf_counter()
        try:
            r = httpx.post(
                f"{API_BASE}/api/v2/generate-quote-reply",
                headers={"Content-Type": "application/json"},
                json={"tenantId": tenant_id, "customerMessage": query},
                timeout=30,
            )
            elapsed = time.perf_counter() - t0
        except Exception as e:
            elapsed = time.perf_counter() - t0
            results.append({
                "query": query or "(empty)",
                "time_s": elapsed,
                "status": "ERR",
                "path": "error",
                "hit": False,
                "expected_hit": EXPECTED_HIT[i] if i < len(EXPECTED_HIT) else False,
            })
            continue

        # Prefer server-reported time if present
        x_time = r.headers.get("X-Response-Time") or r.headers.get("x-response-time")
        if x_time and x_time.endswith("s"):
            try:
                elapsed = float(x_time[:-1])
            except ValueError:
                pass
        path = r.headers.get("X-Retrieval-Path") or r.headers.get("x-retrieval-path") or "unknown"
        faq_hit = (r.headers.get("X-Faq-Hit") or r.headers.get("x-faq-hit") or "").strip().lower() == "true"

        expected = EXPECTED_HIT[i] if i < len(EXPECTED_HIT) else False
        results.append({
            "query": query or "(empty)",
            "time_s": elapsed,
            "status": "HIT" if faq_hit else "FALL",
            "path": path,
            "hit": faq_hit,
            "expected_hit": expected,
        })

    # Table
    print("Query                              | Time    | Status  | Path")
    print("-" * 75)
    for r in results:
        q = (r["query"][:32] + "..") if len(r["query"]) > 34 else r["query"]
        q = q.ljust(34)
        t = f"{r['time_s']:.2f}s".ljust(7)
        st = ("✅ " + r["status"]).ljust(8) if r["status"] == "HIT" else ("   " + r["status"]).ljust(8)
        print(f'"{q}" | {t} | {st} | {r["path"]}')
    print()

    # Summary
    times = [r["time_s"] for r in results]
    n = len(times)
    avg_t = sum(times) / n if n else 0
    max_t = max(times) if times else 0
    under_15 = sum(1 for t in times if t < 1.5)
    under_20 = sum(1 for t in times if t < 2.0)
    correct = sum(1 for r in results if r.get("hit") == r.get("expected_hit"))
    accuracy = (correct / n * 100) if n else 0

    print("Summary:")
    print(f"  Avg response time: {avg_t:.2f}s")
    print(f"  Max response time: {max_t:.2f}s")
    print(f"  Queries under 1.5s: {under_15}/{n} ({100*under_15/n:.0f}%)")
    print(f"  Queries under 2.0s: {under_20}/{n} ({100*under_20/n:.0f}%)  ← MUST BE 100%")
    print(f"  Accuracy: {correct}/{n} ({accuracy:.0f}%)")
    print()

    # Fail conditions
    fail = False
    if max_t > 2.5:
        print(f"FAIL: At least one query took > 2.5s (max={max_t:.2f}s)")
        fail = True
    if accuracy < 85:
        print(f"FAIL: Accuracy below 85% (got {accuracy:.0f}%)")
        fail = True
    if under_20 < n:
        print(f"FAIL: Not all queries under 2.0s ({under_20}/{n})")
        fail = True

    if fail:
        sys.exit(1)
    print("PASS: All benchmark checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
