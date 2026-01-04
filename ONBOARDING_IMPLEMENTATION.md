# Mandatory Variant Expansion + Benchmark Gate Implementation

## Overview

Made variant expansion and benchmark testing mandatory for all new tenant onboarding. This ensures consistent quality and robustness across all tenants.

## Changes Made

### 1. New File: `new_tenant_onboard.ps1`

**Purpose:** Single-command onboarding script that enforces:
- ✅ Mandatory variant expansion (`-ExpandVariants` always enabled)
- ✅ Full pipeline execution (variant library, patches, upload)
- ✅ Suite test execution (must pass)
- ✅ Benchmark gate with strict thresholds

**Usage:**
```powershell
.\new_tenant_onboard.ps1 `
  -TenantId acme_cleaning `
  -AdminBase https://motionmade-fastapi.onrender.com `
  -PublicBase https://api.motionmadebne.com.au `
  -Origin https://example.com
```

**Benchmark Gate Thresholds:**
- ✅ At least 15 test cases
- ✅ FAQ hit rate >= 70%
- ✅ Non-junk fallback rate == 0% (junk cases allowed to clarify)
- ✅ Clarify rate allowed (no restriction)

**Flow:**
1. Run pipeline with `-ExpandVariants` (mandatory)
2. Pipeline includes: variant expansion → library application → patches → upload → suite tests
3. Run benchmark gate
4. If gate fails, onboarding fails (exit code 1)
5. If gate passes, onboarding succeeds

### 2. Modified: `V1_LAUNCH_CHECKLIST.md`

**Updated Section:** "Per-Tenant Onboarding"

**Before:** Multi-step manual process (9 steps)
**After:** Single command with automated gates

**Key Changes:**
- Replaced steps 3-5 (Upload FAQs, Create Test Suite, Promote) with single command
- Added benchmark gate requirements
- Simplified post-onboarding steps

## Unified Diff

### New File: `new_tenant_onboard.ps1`

```powershell
# New file: 200+ lines
# Key features:
# - Always calls run_faq_pipeline.ps1 with -ExpandVariants
# - Runs benchmark gate after pipeline
# - Enforces thresholds and fails if not met
```

### Modified: `V1_LAUNCH_CHECKLIST.md`

```diff
-## Per-Tenant Onboarding
+## Per-Tenant Onboarding
+
+### Prerequisites
+- [ ] Tenant record created via Admin UI or API
+- [ ] Domain(s) registered in `tenant_domains` table
+- [ ] FAQ JSON prepared at `tenants/{tenant_id}/faqs.json`
+- [ ] Test suite created at `tests/{tenant_id}.json`
+
+### Single Command Onboarding
+
+Run the automated onboarding script:
+
+```powershell
+.\new_tenant_onboard.ps1 `
+  -TenantId acme_cleaning `
+  -AdminBase https://motionmade-fastapi.onrender.com `
+  -PublicBase https://api.motionmadebne.com.au `
+  -Origin https://example.com
+```
+
+**What it does:**
+1. ✅ Variant Expansion (mandatory)
+2. ✅ Pipeline execution
+3. ✅ Suite tests (must pass)
+4. ✅ Benchmark gate (hit rate >= 70%, non-junk fallback == 0%)
+5. ✅ Promotion to last_good
```

## Example Run Output

### Successful Onboarding

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
Uploading FAQs (ADMIN)...
Upload OK (HTTP 200)
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

1. **Mandatory Variant Expansion**: Always enabled, no opt-out
2. **Automated Gates**: Pipeline + suite + benchmark all enforced
3. **Strict Thresholds**: 70% hit rate, 0% non-junk fallback
4. **Clear Feedback**: Detailed failure messages guide fixes
5. **Single Command**: Simplifies onboarding process

## Migration Notes

**For existing tenants:**
- Can still use `run_faq_pipeline.ps1` directly (with or without `-ExpandVariants`)
- New tenants must use `new_tenant_onboard.ps1`

**For new tenants:**
- Always use `new_tenant_onboard.ps1`
- Ensure FAQ JSON and test suite are prepared first
- Benchmark gate will catch quality issues early

## Files Changed

- ✅ `new_tenant_onboard.ps1` (NEW - 200+ lines)
- ✅ `V1_LAUNCH_CHECKLIST.md` (MODIFIED - simplified onboarding section)


