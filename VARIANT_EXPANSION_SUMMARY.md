# Variant Expansion Implementation Summary

## Unified Diff

### 1. New File: `tools/expand_variants.py`

Complete new file (360 lines) implementing:
- Deterministic variant generation using templates
- Slang replacements and key-term short forms
- Hard cap of 30 variants per FAQ
- Deduplication and normalization

### 2. Modified: `run_faq_pipeline.ps1`

**Added parameter:**
```powershell
[switch]$ExpandVariants = $false  # Enable automated variant expansion
```

**Added expansion step (lines 160-171):**
```powershell
# Optional: Expand variants if requested
if ($ExpandVariants) {
  Write-Host "Expanding variants (automated expansion)..." -ForegroundColor Cyan
  $expandedPath = Join-Path $tenantDir "faqs_expanded.json"
  $expandScript = Join-Path $root "tools" "expand_variants.py"
  
  python $expandScript --input $faqsSource --output $expandedPath --overwrite
  if ($LASTEXITCODE -ne 0) { throw "expand_variants.py failed" }
  
  # Use expanded file as source for pipeline
  $faqsSource = $expandedPath
  Write-Host "Using expanded FAQs as source: $expandedPath" -ForegroundColor Green
}
```

**Modified source handling:**
- Changed from always using `faqs.json` to using `faqs.json` or `faqs_expanded.json` based on flag

### 3. New File: `verify_variant_expansion.ps1`

Verification script for comparing baseline vs expanded results.

## Test Results

### Expansion Script Test

**Command:**
```bash
python tools/expand_variants.py --input tenants/biz9_real/faqs.json --output tenants/biz9_real/faqs_expanded_test.json --overwrite
```

**Output:**
```
Expanded 20 FAQs
  Variants before: 8
  Variants after: 580
  Average per FAQ: 29.0
Output written to: tenants\biz9_real\faqs_expanded_test.json
```

**Verification:**
- ✅ Expansion works correctly
- ✅ Hard cap respected (29.0 avg, under 30 limit)
- ✅ Significant increase in variants (8 → 580)

### Sample Expanded Variants

**Input FAQ:**
```json
{
  "question": "Oven clean add-on",
  "answer": "Yes - oven cleaning is an optional add-on and costs $89."
}
```

**Expanded Output (first 10 of 29 variants):**
```json
{
  "question": "Oven clean add-on",
  "answer": "Yes - oven cleaning is an optional add-on and costs $89.",
  "variants": [
    "Oven clean add-on?",
    "Oven clean add-on please",
    "Oven clean add-on pls",
    "Oven clean add-on thanks",
    "what is Oven clean add-on",
    "what is Oven clean add-on?",
    "what is Oven clean add-on please",
    "do you Oven clean add-on",
    "can you Oven clean add-on",
    "how much Oven clean add-on",
    ...
  ]
}
```

## Verification Instructions

### Prerequisites

1. **Install Python dependencies:**
   ```bash
   pip install requests
   ```

2. **Ensure ADMIN_TOKEN is set in `.env`**

### Step 1: Baseline Pipeline (No Expansion)

**Command:**
```powershell
cd C:\MM\motionmade-fastapi

.\run_faq_pipeline.ps1 `
  -TenantId biz9_real `
  -AdminBase https://motionmade-fastapi.onrender.com `
  -PublicBase https://api.motionmadebne.com.au `
  -Origin https://motionmadebne.com.au
```

**Expected Output:**
- Pipeline runs without expansion
- FAQs uploaded with original variants
- Suite tests run
- If suite passes: FAQs promoted to last_good

**Then run benchmark:**
```bash
python tools/bench_messy_inputs.py `
  --base-url https://api.motionmadebne.com.au `
  --tenant-id biz9_real `
  --output-dir tools
```

**Expected Benchmark Output:**
```
======================================================================
MESSY INPUT BENCHMARK SUMMARY
======================================================================

Total Cases: [N]
FAQ Hits: [X] ([Y]%)
Clarifies: [A] ([B]%)
Fallbacks: [C] ([D]%)
Fact Hits: [E]
Fact Rewrite Hits: [F]
General OK: [G]
Avg Latency: [L] ms
Cache Hits: [H] ([I]%)

----------------------------------------------------------------------
WORST 5 MISSES (Lowest Scores):
----------------------------------------------------------------------
1. Score: [score] | Branch: [branch] | Input: [input]...
...
```

### Step 2: Expanded Pipeline (With Expansion)

**Command:**
```powershell
.\run_faq_pipeline.ps1 `
  -TenantId biz9_real `
  -AdminBase https://motionmade-fastapi.onrender.com `
  -PublicBase https://api.motionmadebne.com.au `
  -Origin https://motionmadebne.com.au `
  -ExpandVariants
```

**Expected Output:**
```
Expanding variants (automated expansion)...
Expanded 20 FAQs
  Variants before: 8
  Variants after: 580
  Average per FAQ: 29.0
Output written to: tenants\biz9_real\faqs_expanded.json
Using expanded FAQs as source: tenants\biz9_real\faqs_expanded.json
Rebuilt faqs_variants.json from source
...
[Pipeline continues with expanded variants]
```

**Then run benchmark:**
```bash
python tools/bench_messy_inputs.py `
  --base-url https://api.motionmadebne.com.au `
  --tenant-id biz9_real `
  --output-dir tools
```

### Step 3: Compare Results

**Expected Improvements:**
- **Hit Rate**: Should increase (more variants = more potential matches)
- **Clarify Rate**: Should remain similar or decrease slightly
- **Fallback Rate**: Should decrease (fewer queries fall through to general)
- **Worst Misses**: Should have higher scores (closer to threshold)

**THETA Verification:**
```bash
# Verify THETA is still 0.82
grep "THETA" app/retrieval.py
# Should output: THETA = 0.82
```

## Key Features

1. **Deterministic**: Same input always produces same output
2. **Capped**: Max 30 variants per FAQ prevents file size explosion
3. **Safe**: THETA threshold unchanged (0.82), matching remains strict
4. **Optional**: Default disabled, use `-ExpandVariants` to enable
5. **Preserves Logic**: Existing must_variants patching still works

## Files Changed

- ✅ `tools/expand_variants.py` (NEW - 360 lines)
- ✅ `run_faq_pipeline.ps1` (MODIFIED - added ExpandVariants switch)
- ✅ `verify_variant_expansion.ps1` (NEW - verification script)
- ✅ `VARIANT_EXPANSION_IMPLEMENTATION.md` (NEW - documentation)

## Next Steps

1. Run full verification (baseline + expanded + benchmarks)
2. Compare hit/clarify/fallback rates
3. Verify THETA = 0.82 unchanged
4. Review worst misses to see if scores improved
5. If results are positive, enable `-ExpandVariants` for production use


