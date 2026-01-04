#!/usr/bin/env python3
"""
Messy Input Benchmark Runner

Runs test cases against /api/v2/generate-quote-reply and generates a summary report.
"""

import json
import time
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
import requests


def load_test_cases(cases_file: Path) -> List[Dict]:
    """Load test cases from JSON file."""
    with open(cases_file, "r", encoding="utf-8") as f:
        return json.load(f)


def run_benchmark_case(
    base_url: str,
    tenant_id: str,
    case: Dict,
    delay_ms: int = 0
) -> Dict:
    """
    Run a single benchmark case and return results.
    
    Returns dict with:
    - input: original input text
    - name: case name
    - category: case category
    - http_status: HTTP status code
    - x_debug_branch: X-Debug-Branch header value
    - x_faq_hit: X-Faq-Hit header value (as boolean)
    - x_triage_result: X-Triage-Result header value
    - x_retrieval_score: X-Retrieval-Score header value (as float or None)
    - latency_ms: request latency in milliseconds
    - x_cache_hit: X-Cache-Hit header value (as boolean)
    - error: error message if request failed
    """
    input_text = case["input"]
    name = case.get("name", "unknown")
    category = case.get("category", "unknown")
    
    url = f"{base_url}/api/v2/generate-quote-reply"
    payload = {
        "tenantId": tenant_id,
        "customerMessage": input_text
    }
    
    start_time = time.time()
    result = {
        "input": input_text,
        "name": name,
        "category": category,
        "http_status": None,
        "x_debug_branch": None,
        "x_faq_hit": None,
        "x_triage_result": None,
        "x_retrieval_score": None,
        "latency_ms": None,
        "x_cache_hit": None,
        "error": None
    }
    
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        latency_ms = int((time.time() - start_time) * 1000)
        result["http_status"] = response.status_code
        result["latency_ms"] = latency_ms
        
        # Extract headers
        headers = response.headers
        result["x_debug_branch"] = headers.get("X-Debug-Branch", "unknown")
        result["x_faq_hit"] = headers.get("X-Faq-Hit", "false").lower() == "true"
        result["x_triage_result"] = headers.get("X-Triage-Result", "unknown")
        result["x_cache_hit"] = headers.get("X-Cache-Hit", "false").lower() == "true"
        
        score_str = headers.get("X-Retrieval-Score")
        if score_str:
            try:
                result["x_retrieval_score"] = float(score_str)
            except (ValueError, TypeError):
                result["x_retrieval_score"] = None
        else:
            result["x_retrieval_score"] = None
            
    except requests.exceptions.RequestException as e:
        result["error"] = str(e)
        result["latency_ms"] = int((time.time() - start_time) * 1000)
    
    # Delay to avoid rate limiting
    if delay_ms > 0:
        time.sleep(delay_ms / 1000.0)
    
    return result


def calculate_summary(results: List[Dict]) -> Dict:
    """Calculate summary statistics from results."""
    total = len(results)
    if total == 0:
        return {}
    
    hits = sum(1 for r in results if r.get("x_faq_hit") is True)
    clarifies = sum(1 for r in results if r.get("x_debug_branch") == "clarify")
    fallbacks = sum(1 for r in results if r.get("x_debug_branch") in ["fact_miss", "general_fallback"])
    fact_hits = sum(1 for r in results if r.get("x_debug_branch") == "fact_hit")
    fact_rewrite_hits = sum(1 for r in results if r.get("x_debug_branch") == "fact_rewrite_hit")
    general_ok = sum(1 for r in results if r.get("x_debug_branch") == "general_ok")
    
    latencies = [r["latency_ms"] for r in results if r.get("latency_ms") is not None]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    
    cache_hits = sum(1 for r in results if r.get("x_cache_hit") is True)
    cache_hit_rate = round(cache_hits / total, 3) if total > 0 else 0
    
    # Find worst misses (lowest scores, excluding clarifies)
    misses = [
        r for r in results
        if not r.get("x_faq_hit") and r.get("x_retrieval_score") is not None
    ]
    misses.sort(key=lambda x: x.get("x_retrieval_score", 1.0))
    worst_misses = misses[:5]
    
    return {
        "total": total,
        "hits": hits,
        "hit_rate": round(hits / total, 3) if total > 0 else 0,
        "clarifies": clarifies,
        "clarify_rate": round(clarifies / total, 3) if total > 0 else 0,
        "fallbacks": fallbacks,
        "fallback_rate": round(fallbacks / total, 3) if total > 0 else 0,
        "fact_hits": fact_hits,
        "fact_rewrite_hits": fact_rewrite_hits,
        "general_ok": general_ok,
        "avg_latency_ms": round(avg_latency, 1),
        "cache_hits": cache_hits,
        "cache_hit_rate": cache_hit_rate,
        "worst_misses": worst_misses
    }


def print_summary(summary: Dict, results: List[Dict]):
    """Print a concise summary to console."""
    print("\n" + "=" * 70)
    print("MESSY INPUT BENCHMARK SUMMARY")
    print("=" * 70)
    print(f"\nTotal Cases: {summary['total']}")
    print(f"FAQ Hits: {summary['hits']} ({summary['hit_rate']*100:.1f}%)")
    print(f"Clarifies: {summary['clarifies']} ({summary['clarify_rate']*100:.1f}%)")
    print(f"Fallbacks: {summary['fallbacks']} ({summary['fallback_rate']*100:.1f}%)")
    print(f"Fact Hits: {summary['fact_hits']}")
    print(f"Fact Rewrite Hits: {summary['fact_rewrite_hits']}")
    print(f"General OK: {summary['general_ok']}")
    print(f"Avg Latency: {summary['avg_latency_ms']:.1f} ms")
    if summary.get('cache_hits') is not None:
        print(f"Cache Hits: {summary['cache_hits']} ({summary['cache_hit_rate']*100:.1f}%)")
    
    if summary['worst_misses']:
        print("\n" + "-" * 70)
        print("WORST 5 MISSES (Lowest Scores):")
        print("-" * 70)
        for i, miss in enumerate(summary['worst_misses'], 1):
            score = miss.get("x_retrieval_score", "N/A")
            branch = miss.get("x_debug_branch", "unknown")
            input_text = miss.get("input", "")[:50]
            print(f"{i}. Score: {score:.4f} | Branch: {branch:20s} | Input: {input_text}...")
    
    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Run messy input benchmark against FastAPI endpoint"
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL of the API (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--tenant-id",
        default="biz9_real",
        help="Tenant ID to use (default: biz9_real)"
    )
    parser.add_argument(
        "--cases-file",
        type=Path,
        default=Path(__file__).parent / "bench_cases.json",
        help="Path to test cases JSON file"
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=0,
        help="Delay between requests in milliseconds (default: 0, use for prod)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent,
        help="Directory to save results JSON (default: tools/)"
    )
    parser.add_argument(
        "--run-twice",
        action="store_true",
        help="Run benchmark twice (cold + warm cache) and compare"
    )
    
    args = parser.parse_args()
    
    # Load test cases
    if not args.cases_file.exists():
        print(f"Error: Cases file not found: {args.cases_file}")
        sys.exit(1)
    
    cases = load_test_cases(args.cases_file)
    
    if args.run_twice:
        # Run twice: cold then warm
        print("=" * 70)
        print("RUN 1: COLD (no cache)")
        print("=" * 70)
        print(f"Loaded {len(cases)} test cases from {args.cases_file}")
        print(f"Target: {args.base_url}")
        print(f"Tenant: {args.tenant_id}")
        print("\nRunning cold benchmark...")
        
        results_cold = []
        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] {case.get('name', 'unknown')}...", end=" ", flush=True)
            result = run_benchmark_case(
                args.base_url,
                args.tenant_id,
                case,
                delay_ms=args.delay_ms
            )
            results_cold.append(result)
            
            if result.get("error"):
                print(f"ERROR: {result['error']}")
            else:
                branch = result.get("x_debug_branch", "unknown")
                hit = "[HIT]" if result.get("x_faq_hit") else "[MISS]"
                cache = "[CACHE]" if result.get("x_cache_hit") else ""
                print(f"{hit} {cache} {branch}")
        
        summary_cold = calculate_summary(results_cold)
        print_summary(summary_cold, results_cold)
        
        # Small delay between runs
        print("\nWaiting 2 seconds before warm run...")
        time.sleep(2)
        
        print("\n" + "=" * 70)
        print("RUN 2: WARM (with cache)")
        print("=" * 70)
        print("\nRunning warm benchmark...")
        
        results_warm = []
        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] {case.get('name', 'unknown')}...", end=" ", flush=True)
            result = run_benchmark_case(
                args.base_url,
                args.tenant_id,
                case,
                delay_ms=args.delay_ms
            )
            results_warm.append(result)
            
            if result.get("error"):
                print(f"ERROR: {result['error']}")
            else:
                branch = result.get("x_debug_branch", "unknown")
                hit = "[HIT]" if result.get("x_faq_hit") else "[MISS]"
                cache = "[CACHE]" if result.get("x_cache_hit") else ""
                print(f"{hit} {cache} {branch}")
        
        summary_warm = calculate_summary(results_warm)
        print_summary(summary_warm, results_warm)
        
        # Compare
        print("\n" + "=" * 70)
        print("COMPARISON: COLD vs WARM")
        print("=" * 70)
        print(f"Avg Latency:  {summary_cold['avg_latency_ms']:.1f} ms (cold) -> {summary_warm['avg_latency_ms']:.1f} ms (warm)")
        speedup = ((summary_cold['avg_latency_ms'] - summary_warm['avg_latency_ms']) / summary_cold['avg_latency_ms']) * 100 if summary_cold['avg_latency_ms'] > 0 else 0
        print(f"Speedup:      {speedup:.1f}%")
        print(f"Cache Hits:   {summary_warm['cache_hits']} ({summary_warm['cache_hit_rate']*100:.1f}%)")
        print("=" * 70 + "\n")
        
        # Save both results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = args.output_dir / f"bench_results_{timestamp}.json"
        
        output_data = {
            "timestamp": datetime.now().isoformat(),
            "base_url": args.base_url,
            "tenant_id": args.tenant_id,
            "delay_ms": args.delay_ms,
            "cold": {
                "summary": summary_cold,
                "results": results_cold
            },
            "warm": {
                "summary": summary_warm,
                "results": results_warm
            },
            "comparison": {
                "latency_speedup_pct": round(speedup, 1),
                "cache_hit_rate": summary_warm['cache_hit_rate']
            }
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"Results saved to: {output_file}\n")
    else:
        # Single run
        print(f"Loaded {len(cases)} test cases from {args.cases_file}")
        print(f"Target: {args.base_url}")
        print(f"Tenant: {args.tenant_id}")
        if args.delay_ms > 0:
            print(f"Delay: {args.delay_ms} ms between requests")
        print("\nRunning benchmark...")
        
        # Run all cases
        results = []
        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] {case.get('name', 'unknown')}...", end=" ", flush=True)
            result = run_benchmark_case(
                args.base_url,
                args.tenant_id,
                case,
                delay_ms=args.delay_ms
            )
            results.append(result)
            
            # Print quick status
            if result.get("error"):
                print(f"ERROR: {result['error']}")
            else:
                branch = result.get("x_debug_branch", "unknown")
                hit = "[HIT]" if result.get("x_faq_hit") else "[MISS]"
                cache = "[CACHE]" if result.get("x_cache_hit") else ""
                score = result.get("x_retrieval_score")
                score_str = f" (score: {score:.4f})" if score is not None else ""
                print(f"{hit} {cache} {branch}{score_str}")
        
        # Calculate summary
        summary = calculate_summary(results)
        
        # Print summary
        print_summary(summary, results)
        
        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = args.output_dir / f"bench_results_{timestamp}.json"
        
        output_data = {
            "timestamp": datetime.now().isoformat(),
            "base_url": args.base_url,
            "tenant_id": args.tenant_id,
            "delay_ms": args.delay_ms,
            "summary": summary,
            "results": results
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        print(f"\nResults saved to: {output_file}")
        print("=" * 70 + "\n")


if __name__ == "__main__":
    main()

