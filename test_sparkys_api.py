"""Test Sparky's Electrical API with realistic customer questions."""
import json
import urllib.request
import sys

API_URL = "https://api.motionmadebne.com.au/api/v2/generate-quote-reply"
TENANT_ID = "sparkys_electrical"

# Load test cases
with open("test_sparkys_realistic.json", "r") as f:
    tests = json.load(f)

print("=" * 80)
print("SPARKY'S ELECTRICAL - REALISTIC CUSTOMER QUESTION TEST")
print("=" * 80)
print()

results = []
for test in tests:
    question = test["question"]
    expect_hit = test["expect_hit"]
    expected_topic = test["expected_topic"]
    
    # Make API call
    body = json.dumps({
        "tenantId": TENANT_ID,
        "customerMessage": question
    }).encode()
    
    req = urllib.request.Request(API_URL, data=body, headers={"Content-Type": "application/json"})
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            headers = {k.lower(): v for k, v in resp.getheaders()}
            body_text = resp.read().decode()
            
            faq_hit = headers.get("x-faq-hit", "false") == "true"
            score = float(headers.get("x-retrieval-score", 0)) if headers.get("x-retrieval-score") else None
            disambiguated = headers.get("x-disambiguated", "false") == "true"
            branch = headers.get("x-debug-branch", "unknown")
            normalized = headers.get("x-normalized-input", "")
            
            # Check if correct
            correct = (faq_hit == expect_hit)
            
            icon = "[PASS]" if correct else "[FAIL]"
            hit_str = "HIT" if faq_hit else "MISS"
            score_str = f"({score:.3f})" if score else "(n/a)"
            disambig_str = " [DISAMBIG]" if disambiguated else ""
            
            print(f"{icon} [{test['id']}] {hit_str} {score_str}{disambig_str}")
            print(f"       Q: \"{question}\"")
            if normalized:
                print(f"       Normalized: \"{normalized}\"")
            print(f"       Branch: {branch}")
            if not correct:
                print(f"       Expected: {'HIT' if expect_hit else 'MISS'}")
            print()
            
            results.append({
                "test": test,
                "faq_hit": faq_hit,
                "score": score,
                "disambiguated": disambiguated,
                "branch": branch,
                "correct": correct
            })
            
    except Exception as e:
        print(f"[ERROR] [{test['id']}] Failed: {e}")
        print(f"       Q: \"{question}\"")
        print()
        results.append({
            "test": test,
            "faq_hit": False,
            "error": str(e),
            "correct": False
        })

# Summary
print("=" * 80)
print("SUMMARY")
print("=" * 80)

total = len(results)
expected_hits = [r for r in results if r["test"]["expect_hit"]]
actual_hits = [r for r in expected_hits if r["faq_hit"]]
hit_rate = len(actual_hits) / len(expected_hits) * 100 if expected_hits else 0

disambiguated_count = sum(1 for r in results if r.get("disambiguated", False))
wrong_hits = [r for r in results if not r["test"]["expect_hit"] and r["faq_hit"]]
wrong_misses = [r for r in results if r["test"]["expect_hit"] and not r["faq_hit"]]

print(f"Total questions: {total}")
print(f"Expected hits: {len(expected_hits)}")
print(f"Actual hits: {len(actual_hits)}")
print(f"Hit rate: {hit_rate:.1f}%")
print(f"Disambiguated: {disambiguated_count}")
print(f"Wrong hits (should miss but hit): {len(wrong_hits)}")
print(f"Wrong misses (should hit but missed): {len(wrong_misses)}")
print()

if wrong_hits:
    print("WRONG HITS (should miss but hit):")
    for r in wrong_hits:
        print(f"  - [{r['test']['id']}] \"{r['test']['question']}\"")
    print()

if wrong_misses:
    print("WRONG MISSES (should hit but missed):")
    for r in wrong_misses:
        score = r.get("score", "n/a")
        print(f"  - [{r['test']['id']}] \"{r['test']['question']}\" (score: {score})")
    print()

if disambiguated_count > 0:
    print("DISAMBIGUATED QUERIES:")
    for r in results:
        if r.get("disambiguated", False):
            print(f"  - [{r['test']['id']}] \"{r['test']['question']}\" -> {r['branch']}")
    print()

print("=" * 80)

