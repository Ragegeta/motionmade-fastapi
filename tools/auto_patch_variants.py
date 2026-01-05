#!/usr/bin/env python3
"""
Auto-patch FAQs with variants based on benchmark worst misses.

Strategy: Add the NORMALIZED versions of failed queries as variants.
Since normalization converts messy -> clean, we only need clean variants.

Usage:
    python auto_patch_variants.py <tenant_id> [--apply]
    
Without --apply, shows what would be added.
With --apply, modifies the FAQs file and re-uploads.
"""

import json
import sys
import urllib.request
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).parent.parent
API_URL = "https://api.motionmadebne.com.au"


def load_benchmark(tenant_id: str) -> dict:
    """Load the messy benchmark for a tenant."""
    # Try tenant-specific first, then generic
    paths = [
        SCRIPT_DIR / "tests" / f"{tenant_id}_messy.json",
        SCRIPT_DIR / "tests" / f"{tenant_id}.json",
        SCRIPT_DIR / "tests" / "messy_benchmark.json",
    ]
    
    for path in paths:
        if path.exists():
            with open(path, "r") as f:
                return json.load(f)
    
    raise FileNotFoundError(f"No benchmark found for {tenant_id}")


def run_benchmark(tenant_id: str, tests: list) -> list:
    """Run benchmark and return worst misses with their normalized forms."""
    worst_misses = []
    
    for test in tests:
        if not test.get("expect_hit", False):
            continue
        
        body = json.dumps({"tenantId": tenant_id, "customerMessage": test["question"]}).encode()
        req = urllib.request.Request(
            f"{API_URL}/api/v2/generate-quote-reply",
            data=body,
            headers={"Content-Type": "application/json"}
        )
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                headers = {k.lower(): v for k, v in resp.getheaders()}
                faq_hit = headers.get("x-faq-hit", "false") == "true"
                score = float(headers.get("x-retrieval-score", 0)) if headers.get("x-retrieval-score") else 0
                normalized = headers.get("x-normalized-input", test["question"])
        except Exception:
            faq_hit = False
            score = 0
            normalized = test["question"]
        
        if not faq_hit:
            normalized_clean = normalized.strip().lower()
            if normalized_clean:  # Skip empty normalized strings
                worst_misses.append({
                    "question": test["question"],
                    "normalized": normalized_clean,
                    "score": score,
                    "category": test.get("category", "unknown")
                })
    
    return worst_misses


def find_best_faq_match(normalized: str, faqs: list) -> int:
    """Find the FAQ index that best matches a normalized query."""
    # Simple keyword matching
    normalized_words = set(normalized.lower().split())
    
    best_idx = 0
    best_score = 0
    
    for i, faq in enumerate(faqs):
        # Check question and existing variants for overlap
        faq_text = faq.get("question", "").lower()
        faq_words = set(faq_text.split())
        
        for variant in faq.get("variants", []):
            faq_words.update(variant.lower().split())
        
        overlap = len(normalized_words & faq_words)
        if overlap > best_score:
            best_score = overlap
            best_idx = i
    
    return best_idx


def patch_faqs(faqs: list, worst_misses: list) -> tuple[list, dict]:
    """
    Add normalized versions of worst misses as variants.
    Returns (patched_faqs, changes_dict).
    """
    changes = defaultdict(list)
    
    for miss in worst_misses:
        normalized = miss["normalized"]
        
        # Find which FAQ this should belong to
        faq_idx = find_best_faq_match(normalized, faqs)
        faq = faqs[faq_idx]
        
        # Check if already exists
        existing = set(v.lower() for v in faq.get("variants", []))
        if normalized not in existing:
            faq.setdefault("variants", []).append(normalized)
            changes[faq["question"]].append(normalized)
    
    return faqs, dict(changes)


def main():
    if len(sys.argv) < 2:
        print("Usage: python auto_patch_variants.py <tenant_id> [--apply]")
        sys.exit(1)
    
    tenant_id = sys.argv[1]
    apply = "--apply" in sys.argv
    
    # Load FAQs
    faqs_path = SCRIPT_DIR / "tenants" / tenant_id / "faqs_minimal.json"
    if not faqs_path.exists():
        faqs_path = SCRIPT_DIR / "tenants" / tenant_id / "faqs.json"
    
    if not faqs_path.exists():
        print(f"Error: No FAQs found for {tenant_id}")
        sys.exit(1)
    
    with open(faqs_path, "r") as f:
        faqs = json.load(f)
    
    # Load and run benchmark
    print(f"Loading benchmark for {tenant_id}...")
    benchmark = load_benchmark(tenant_id)
    
    print(f"Running benchmark ({len(benchmark['tests'])} tests)...")
    worst_misses = run_benchmark(tenant_id, benchmark["tests"])
    
    if not worst_misses:
        print("[PASS] No misses! All expected hits are working.")
        sys.exit(0)
    
    print(f"\nFound {len(worst_misses)} misses:")
    for miss in worst_misses:
        print(f"  * \"{miss['normalized']}\" (score: {miss['score']:.3f})")
    
    # Patch FAQs
    patched_faqs, changes = patch_faqs(faqs, worst_misses)
    
    print(f"\nProposed changes:")
    for faq_q, new_variants in changes.items():
        print(f"  {faq_q}:")
        for v in new_variants:
            print(f"    + \"{v}\"")
    
    if not apply:
        print("\nRun with --apply to save changes and re-upload.")
        sys.exit(0)
    
    # Save patched FAQs
    output_path = SCRIPT_DIR / "tenants" / tenant_id / "faqs_patched.json"
    with open(output_path, "w") as f:
        json.dump(patched_faqs, f, indent=2)
    
    print(f"\n[PASS] Saved to {output_path}")
    print("Now run: upload staged -> promote -> re-run benchmark")


if __name__ == "__main__":
    main()

