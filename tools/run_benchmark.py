#!/usr/bin/env python3
"""
Run messy benchmark and identify worst misses for targeted fixes.

Usage:
    python run_benchmark.py <tenant_id> [--api-url=<url>]
"""

import json
import sys
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

SCRIPT_DIR = Path(__file__).parent.parent
BENCHMARK_PATH = SCRIPT_DIR / "tests" / "messy_benchmark.json"
DEFAULT_API_URL = "https://api.motionmadebne.com.au"


def run_test(api_url: str, tenant_id: str, question: str) -> dict:
    """Run a single test and return results."""
    url = f"{api_url}/api/v2/generate-quote-reply"
    body = json.dumps({"tenantId": tenant_id, "customerMessage": question}).encode()
    
    req = Request(url, data=body, headers={"Content-Type": "application/json"})
    
    try:
        with urlopen(req, timeout=30) as resp:
            headers = {k.lower(): v for k, v in resp.getheaders()}
            body_text = resp.read().decode()
            
            return {
                "status": resp.status,
                "faq_hit": headers.get("x-faq-hit", "false") == "true",
                "score": float(headers.get("x-retrieval-score", 0)) if headers.get("x-retrieval-score") else None,
                "branch": headers.get("x-debug-branch", "unknown"),
                "normalized": headers.get("x-normalized-input", ""),
                "is_clarify": "rephrase" in body_text.lower(),
            }
    except Exception as e:
        return {"status": 0, "error": str(e), "faq_hit": False, "score": None, "branch": "error"}


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_benchmark.py <tenant_id> [--api-url=<url>]")
        sys.exit(1)
    
    tenant_id = sys.argv[1]
    api_url = DEFAULT_API_URL
    
    for arg in sys.argv[2:]:
        if arg.startswith("--api-url="):
            api_url = arg.split("=", 1)[1]
    
    # Load benchmark
    with open(BENCHMARK_PATH, "r") as f:
        benchmark = json.load(f)
    
    tests = benchmark["tests"]
    thresholds = benchmark["pass_thresholds"]
    
    print(f"{'='*60}")
    print(f"MESSY BENCHMARK: {tenant_id}")
    print(f"Tests: {len(tests)} | Min hit rate: {thresholds['min_hit_rate']*100}%")
    print(f"{'='*60}\n")
    
    results = []
    worst_misses = []  # Queries that should hit but didn't
    
    for test in tests:
        result = run_test(api_url, tenant_id, test["question"])
        
        # Determine pass/fail
        expected_hit = test.get("expect_hit", False)
        expected_branch = test.get("expect_branch")
        
        actual_hit = result["faq_hit"]
        actual_branch = "clarify" if result["is_clarify"] else result["branch"]
        
        passed = True
        reason = ""
        
        if expected_hit and not actual_hit:
            passed = False
            reason = f"Expected HIT, got MISS (score: {result['score']})"
            worst_misses.append({
                "question": test["question"],
                "category": test["category"],
                "score": result["score"],
                "normalized": result["normalized"],
            })
        elif not expected_hit and actual_hit:
            passed = False
            reason = "Expected MISS, got HIT (wrong match)"
        elif expected_branch and actual_branch != expected_branch:
            passed = False
            reason = f"Expected branch '{expected_branch}', got '{actual_branch}'"
        
        icon = "✅" if passed else "❌"
        hit_str = "HIT" if actual_hit else "MISS"
        score_str = f"({result['score']:.3f})" if result['score'] else "(n/a)"
        
        print(f"  {icon} [{test['id']}] {hit_str} {score_str} - {test['question'][:50]}")
        if not passed:
            print(f"       → {reason}")
        
        results.append({"test": test, "result": result, "passed": passed})
    
    # Calculate metrics
    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    
    expect_hit_tests = [r for r in results if r["test"].get("expect_hit")]
    actual_hits = sum(1 for r in expect_hit_tests if r["result"]["faq_hit"])
    hit_rate = actual_hits / len(expect_hit_tests) if expect_hit_tests else 0
    
    expect_miss_tests = [r for r in results if not r["test"].get("expect_hit")]
    wrong_hits = sum(1 for r in expect_miss_tests if r["result"]["faq_hit"])
    wrong_hit_rate = wrong_hits / len(expect_miss_tests) if expect_miss_tests else 0
    
    # Fallback rate (expected hits that got fallback branch)
    fallbacks = [r for r in expect_hit_tests if r["result"]["branch"] in ("general_fallback", "fact_miss") and not r["result"]["is_clarify"]]
    fallback_rate = len(fallbacks) / len(expect_hit_tests) if expect_hit_tests else 0
    
    # Summary
    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")
    print(f"  Tests passed: {passed_count}/{total} ({passed_count/total*100:.0f}%)")
    print(f"  Hit rate: {hit_rate*100:.1f}% (threshold: {thresholds['min_hit_rate']*100}%)")
    print(f"  Fallback rate: {fallback_rate*100:.1f}% (threshold: {thresholds['max_fallback_rate']*100}%)")
    print(f"  Wrong hit rate: {wrong_hit_rate*100:.1f}% (threshold: {thresholds['max_wrong_hit_rate']*100}%)")
    
    # Gate check
    gate_pass = (
        hit_rate >= thresholds["min_hit_rate"] and
        fallback_rate <= thresholds["max_fallback_rate"] and
        wrong_hit_rate <= thresholds["max_wrong_hit_rate"]
    )
    
    print(f"\n{'='*60}")
    if gate_pass:
        print("✅ BENCHMARK GATE: PASS")
    else:
        print("❌ BENCHMARK GATE: FAIL")
    print(f"{'='*60}")
    
    # Show worst misses for targeted fixes
    if worst_misses:
        # Sort by score descending (highest score misses are closest to threshold)
        worst_misses.sort(key=lambda x: x["score"] or 0, reverse=True)
        
        print(f"\n{'='*60}")
        print("WORST MISSES (add these as variants)")
        print(f"{'='*60}")
        
        for miss in worst_misses[:10]:
            print(f"\n  Question: \"{miss['question']}\"")
            print(f"  Category: {miss['category']}")
            print(f"  Score: {miss['score']}")
            print(f"  Normalized: \"{miss['normalized']}\"")
            print(f"  → Add as variant: \"{miss['normalized']}\" or \"{miss['question'].lower()}\"")
    
    return 0 if gate_pass else 1


if __name__ == "__main__":
    sys.exit(main())

