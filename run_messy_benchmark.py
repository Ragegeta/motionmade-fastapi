import json
import urllib.request
import sys
from pathlib import Path

API_URL = 'https://api.motionmadebne.com.au'
TENANT_ID = 'sparkys_electrical'

# Load benchmark
benchmark_path = Path(__file__).parent / 'tests' / f'{TENANT_ID}_messy.json'
with open(benchmark_path, 'r') as f:
    benchmark = json.load(f)

tests = benchmark['tests']
results = []
worst_misses = []

print(f'Running {len(tests)} tests...\n')

for test in tests:
    body = json.dumps({'tenantId': TENANT_ID, 'customerMessage': test['question']}).encode()
    req = urllib.request.Request(
        f'{API_URL}/api/v2/generate-quote-reply',
        data=body,
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            headers = {k.lower(): v for k, v in resp.getheaders()}
            body_text = resp.read().decode()
            
            faq_hit = headers.get('x-faq-hit', 'false') == 'true'
            score = float(headers.get('x-retrieval-score', 0)) if headers.get('x-retrieval-score') else None
            normalized = headers.get('x-normalized-input', '')
            branch = headers.get('x-debug-branch', 'unknown')
            is_clarify = 'rephrase' in body_text.lower()
    except Exception as e:
        faq_hit = False
        score = None
        normalized = ''
        branch = 'error'
        is_clarify = False
    
    expected_hit = test.get('expect_hit', False)
    
    if expected_hit and not faq_hit:
        passed = False
        worst_misses.append({
            'id': test['id'],
            'question': test['question'],
            'normalized': normalized,
            'score': score
        })
    elif not expected_hit and faq_hit:
        passed = False
    else:
        passed = True
    
    icon = '[PASS]' if passed else '[FAIL]'
    hit_str = 'HIT' if faq_hit else 'MISS'
    score_str = f'({score:.3f})' if score else '(n/a)'
    
    print(f'  {icon} [{test["id"]}] {hit_str} {score_str} - {test["question"][:40]}')
    if not passed and expected_hit:
        print(f'       Normalized: "{normalized}"')
    
    results.append({'test': test, 'passed': passed, 'faq_hit': faq_hit})

# Summary
passed_count = sum(1 for r in results if r['passed'])
total = len(results)

expect_hit = [r for r in results if r['test'].get('expect_hit')]
actual_hits = sum(1 for r in expect_hit if r['faq_hit'])
hit_rate = actual_hits / len(expect_hit) if expect_hit else 0

print(f'\n{"="*50}')
print(f'RESULTS: {passed_count}/{total} passed ({passed_count/total*100:.0f}%)')
print(f'Hit rate: {hit_rate*100:.1f}%')
print(f'{"="*50}')

if worst_misses:
    print(f'\nWORST MISSES (add these normalized forms as variants):')
    worst_misses.sort(key=lambda x: x['score'] or 0, reverse=True)
    for miss in worst_misses:
        print(f'  * "{miss["normalized"]}" (from: "{miss["question"]}")')

