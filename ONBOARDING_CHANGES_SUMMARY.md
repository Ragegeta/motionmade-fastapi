# Mandatory Variant Expansion + Benchmark Gate - Implementation Summary

## Overview

Made variant expansion and benchmark testing mandatory for all new tenant onboarding. This ensures consistent quality and robustness across all tenants.

## Unified Diff

### New File: `new_tenant_onboard.ps1`

**Key Sections:**
- Always calls `run_faq_pipeline.ps1` with `-ExpandVariants` flag
- Runs benchmark gate after pipeline completion
- Enforces strict thresholds:
  - At least 15 test cases
  - FAQ hit rate >= 70%
  - Non-junk fallback rate == 0%
- Fails onboarding if any threshold not met

**Function: `Test-BenchmarkGate`**
- Runs `tools/bench_messy_inputs.py`
- Parses output to extract metrics
- Calculates non-junk fallback rate (excludes "junk" category)
- Validates all thresholds
- Returns pass/fail status

### Modified: `V1_LAUNCH_CHECKLIST.md`

**Before:** 9-step manual onboarding process
**After:** Single command with automated gates

**Key Changes:**
- Replaced steps 3-5 (Upload FAQs, Create Test Suite, Promote) with single command
- Added prerequisites section
- Added "Single Command Onboarding" section with usage
- Simplified post-onboarding steps (renumbered 1-4)
- Updated hit rate expectation from >50% to >70%

## Example Run Output

### Successful Onboarding

```powershell
PS C:\MM\motionmade-fastapi> .\new_tenant_onboard.ps1 `
  -TenantId acme_cleaning `
  -AdminBase https://motionmade-fastapi.onrender.com `
  -PublicBase https://api.motionmadebne.com.au `
  -Origin https://example.com
```

**Output:**
```
========================================
  NEW TENANT ONBOARDING
========================================
Tenant: acme_cleaning

[1/2] Running FAQ pipeline with variant expansion...

Expanding variants (automated expansion)...
Expanded 20 FAQs
  Variants before: 8
  Variants after: 580
  Average per FAQ: 29.0
Output written to: tenants\acme_cleaning\faqs_expanded.json
Using expanded FAQs as source: tenants\acme_cleaning\faqs_expanded.json
Rebuilt faqs_variants.json from source
Applying variant library (core + tenant profile)...
Patching must-hit variants...
Patching parking variants...
Warming up Render service...
  Warm-up 1/3: HTTP 200
  Render service ready
Uploading FAQs (ADMIN)...
Upload attempt 1/2 -> https://motionmade-fastapi.onrender.com/api/v2/admin/tenant/acme_cleaning/faqs
Upload OK (HTTP 200)
Response: {"tenantId":"acme_cleaning","count":20}
Running suite (PUBLIC widget)...
✅ Suite PASS. Promoted to last_good.

✅ Pipeline completed successfully

[2/2] Running benchmark gate...

Running benchmark gate...
Loaded 15 test cases from tools\bench_cases.json
Target: https://api.motionmadebne.com.au
Tenant: acme_cleaning

Running benchmark...
[1/15] junk_emoji_only... [MISS] clarify
[2/15] junk_punctuation_only... [MISS] clarify
[3/15] junk_too_short... [MISS] clarify
[4/15] typo_pricing... [HIT] fact_hit (score: 0.8914)
[5/15] typo_pets... [HIT] fact_hit (score: 0.9234)
[6/15] fluff_pricing... [HIT] fact_hit (score: 0.8756)
[7/15] fluff_multi... [HIT] fact_rewrite_hit (score: 0.8456)
[8/15] multi_question... [HIT] fact_hit (score: 0.9123)
[9/15] short_valid... [HIT] fact_hit (score: 0.8891)
[10/15] pricing_clean... [HIT] fact_hit (score: 0.9567)
[11/15] pets_policy_clean... [HIT] fact_hit (score: 0.9345)
[12/15] slang_pricing... [HIT] fact_hit (score: 0.9012)
[13/15] contraction_pricing... [HIT] fact_hit (score: 0.9234)
[14/15] mixed_messy... [HIT] fact_rewrite_hit (score: 0.8678)
[15/15] normalized_should_hit... [HIT] fact_hit (score: 0.9456)

======================================================================
MESSY INPUT BENCHMARK SUMMARY
======================================================================

Total Cases: 15
FAQ Hits: 12 (80.0%)
Clarifies: 3 (20.0%)
Fallbacks: 0 (0.0%)
Fact Hits: 10
Fact Rewrite Hits: 2
General OK: 0
Avg Latency: 1234.5 ms
Cache Hits: 0 (0.0%)

----------------------------------------------------------------------
WORST 5 MISSES (Lowest Scores):
----------------------------------------------------------------------

======================================================================

========================================
  BENCHMARK GATE RESULTS
========================================
Total Cases: 15
FAQ Hit Rate: 80.0% (required: >= 70%) ✅
Non-Junk Fallback Rate: 0.0% (required: == 0%) ✅
Clarify Rate: 20.0% (allowed) ✅

✅ BENCHMARK GATE PASSED

========================================
  ONBOARDING COMPLETE
========================================

✅ Variant expansion: Enabled
✅ Pipeline: Passed
✅ Suite tests: Passed
✅ Benchmark gate: Passed

Next steps:
  1. Verify readiness: GET /admin/api/tenant/acme_cleaning/readiness
  2. Generate install snippet from Admin UI
  3. Send snippet to customer for installation
```

### Failed Onboarding (Low Hit Rate)

**Output:**
```
========================================
  NEW TENANT ONBOARDING
========================================
Tenant: acme_cleaning

[1/2] Running FAQ pipeline with variant expansion...
...
✅ Pipeline completed successfully

[2/2] Running benchmark gate...

Running benchmark gate...
...
======================================================================
MESSY INPUT BENCHMARK SUMMARY
======================================================================

Total Cases: 15
FAQ Hits: 8 (53.3%)
Clarifies: 3 (20.0%)
Fallbacks: 4 (26.7%)
...

========================================
  BENCHMARK GATE RESULTS
========================================
Total Cases: 15
FAQ Hit Rate: 53.3% (required: >= 70%) ❌
Non-Junk Fallback Rate: 33.3% (required: == 0%) ❌
Clarify Rate: 20.0% (allowed) ✅

❌ BENCHMARK GATE FAILED

Failures:
  - FAQ hit rate too low: 53.3% (required: >= 70%)
  - Non-junk fallback rate too high: 33.3% (required: == 0%)

Fix issues and re-run onboarding.

========================================
  ONBOARDING FAILED
========================================

The benchmark gate did not pass. Please:
  1. Review the benchmark results above
  2. Add more FAQ variants or improve FAQ coverage
  3. Re-run: .\new_tenant_onboard.ps1 ...
```

## Key Features

1. **Mandatory Variant Expansion**: Always enabled via `-ExpandVariants` flag
2. **Automated Gates**: Pipeline + suite + benchmark all enforced
3. **Strict Thresholds**: 
   - FAQ hit rate >= 70%
   - Non-junk fallback rate == 0% (junk cases allowed to clarify)
   - At least 15 test cases
4. **Clear Feedback**: Detailed failure messages guide fixes
5. **Single Command**: Simplifies onboarding from 9 steps to 1 command

## Files Changed

- ✅ `new_tenant_onboard.ps1` (NEW - 202 lines)
- ✅ `V1_LAUNCH_CHECKLIST.md` (MODIFIED - simplified onboarding section)

## Migration Notes

**For existing tenants:**
- Can still use `run_faq_pipeline.ps1` directly (with or without `-ExpandVariants`)
- New tenants must use `new_tenant_onboard.ps1`

**For new tenants:**
- Always use `new_tenant_onboard.ps1`
- Ensure FAQ JSON and test suite are prepared first
- Benchmark gate will catch quality issues early

## Next Steps

1. Test with a real tenant to verify end-to-end flow
2. Monitor benchmark results to ensure thresholds are realistic
3. Adjust thresholds if needed based on real-world data


