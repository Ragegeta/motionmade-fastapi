#!/usr/bin/env python3
"""
Quick benchmark for hybrid retrieval.
Run: python tools/quick_benchmark.py sparkys_electrical
"""

import sys
import json
import urllib.request
from collections import defaultdict

API_URL = "https://api.motionmadebne.com.au"

TESTS = [
    # Should HIT
    ("how much do you charge", "hit", "pricing"),
    ("ur prices pls", "hit", "pricing"),
    ("can u install ceiling fans", "hit", "services"),
    ("do u do smoke alarms", "hit", "services"),
    ("can you do switchboards", "hit", "services"),
    ("wat do u do", "hit", "services"),
    ("do u service logan", "hit", "area"),
    ("what areas do you cover", "hit", "area"),
    ("can you come today", "hit", "booking"),
    ("urgent", "hit", "emergency"),
    ("i have no power", "hit", "emergency"),
    ("are you licensed", "hit", "trust"),
    ("r u insured", "hit", "trust"),
    
    # Should MISS
    ("do you do plumbing", "miss", "wrong_service"),
    ("can you paint my house", "miss", "wrong_service"),
    ("do you do roofing", "miss", "wrong_service"),
    
    # Should CLARIFY
    ("???", "clarify", "junk"),
    ("asdf", "clarify", "junk"),
]


def call_api(tenant_id: str, query: str) -> dict:
    body = json.dumps({"tenantId": tenant_id, "customerMessage": query}).encode()
    req = urllib.request.Request(
        f"{API_URL}/api/v2/generate-quote-reply",
        data=body,
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            headers = {k.lower(): v for k, v in resp.getheaders()}
            body_text = resp.read().decode()
            
            return {
                "faq_hit": headers.get("x-faq-hit", "false") == "true",
                "score": headers.get("x-retrieval-score", "0"),
                "stage": headers.get("x-retrieval-stage", "?"),
                "candidates": headers.get("x-candidate-count", "0"),
                "selector": headers.get("x-selector-called", "false"),
                "confidence": headers.get("x-selector-confidence", "0"),
                "is_clarify": "rephrase" in body_text.lower()
            }
    except Exception as e:
        return {"error": str(e)}


def main():
    tenant_id = sys.argv[1] if len(sys.argv) > 1 else "sparkys_electrical"
    
    print(f"{'='*60}")
    print(f"  BENCHMARK: {tenant_id}")
    print(f"{'='*60}\n")
    
    results = {"hit": 0, "miss": 0, "clarify": 0, "wrong": 0}
    by_category = defaultdict(lambda: {"pass": 0, "fail": 0})
    failures = []
    
    for query, expected, category in TESTS:
        r = call_api(tenant_id, query)
        
        if r.get("error"):
            actual = "error"
        elif r.get("is_clarify"):
            actual = "clarify"
        elif r.get("faq_hit"):
            actual = "hit"
        else:
            actual = "miss"
        
        # Determine pass/fail
        if expected == "hit":
            passed = actual == "hit"
        elif expected == "miss":
            passed = actual in ("miss", "clarify")  # Both OK for should-miss
        elif expected == "clarify":
            passed = actual in ("miss", "clarify")
        else:
            passed = False
        
        results[actual] = results.get(actual, 0) + 1
        by_category[category]["pass" if passed else "fail"] += 1
        
        icon = "[OK]" if passed else "[FAIL]"
        stage_info = f"[{r.get('stage', '?')}]" if r.get('stage') else ""
        score_info = f"({r.get('score', '?')})" if r.get('score') else ""
        
        print(f"  {icon} {actual:7} {score_info:8} {stage_info:20} - {query[:40]}")
        
        if not passed:
            failures.append({"query": query, "expected": expected, "actual": actual, "category": category})
    
    # Summary
    total = len(TESTS)
    expected_hits = sum(1 for _, e, _ in TESTS if e == "hit")
    actual_hits = results.get("hit", 0)
    hit_rate = (actual_hits / expected_hits * 100) if expected_hits > 0 else 0
    
    expected_misses = sum(1 for _, e, _ in TESTS if e in ("miss", "clarify"))
    wrong_hits = sum(1 for f in failures if f["expected"] in ("miss", "clarify") and f["actual"] == "hit")
    wrong_hit_rate = (wrong_hits / expected_misses * 100) if expected_misses > 0 else 0
    
    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Hit rate:       {actual_hits}/{expected_hits} ({hit_rate:.1f}%)")
    print(f"  Wrong hit rate: {wrong_hits}/{expected_misses} ({wrong_hit_rate:.1f}%)")
    print(f"  Total passed:   {total - len(failures)}/{total}")
    
    # By category
    print(f"\n  By category:")
    for cat, stats in sorted(by_category.items()):
        total_cat = stats["pass"] + stats["fail"]
        pct = (stats["pass"] / total_cat * 100) if total_cat > 0 else 0
        icon = "[OK]" if stats["fail"] == 0 else "[WARN]"
        print(f"    {icon} {cat:20} {stats['pass']}/{total_cat} ({pct:.0f}%)")
    
    # Failures
    if failures:
        print(f"\n  Failures:")
        for f in failures[:10]:
            print(f"    - '{f['query']}' expected {f['expected']}, got {f['actual']}")
    
    # Final verdict
    print(f"\n{'='*60}")
    if hit_rate >= 75 and wrong_hit_rate == 0:
        print("  [PASS] Hit rate >= 75% and wrong hit rate = 0%")
    else:
        print(f"  [FAIL] Hit rate {hit_rate:.1f}% (need 75%), wrong hits {wrong_hit_rate:.1f}% (need 0%)")
    print(f"{'='*60}\n")
    
    return 0 if (hit_rate >= 75 and wrong_hit_rate == 0) else 1


if __name__ == "__main__":
    sys.exit(main())

