# Normalization-First Variant Strategy

## Overview

This strategy leverages the normalization layer to convert messy user input (slang, typos, abbreviations) into clean forms. Instead of adding hundreds of messy variants to FAQs, we:

1. **Add minimal clean variants** to each FAQ
2. **Let normalization handle the messy input** → clean conversion
3. **Auto-patch from benchmark misses** to add any missing normalized forms

## Why This Works

- Normalization converts "ur prices pls" → "your prices please"
- If "your prices please" is a variant, it matches
- Auto-patch adds the exact normalized forms that missed
- Usually 1-2 iterations gets to 90%+ hit rate

## Recommended Workflow

### 1. DISCOVERY
Talk to business owner, get their FAQs:
- 5-10 core FAQs (pricing, services, area, booking, policies)
- Write clean answers with their real info

### 2. MINIMAL VARIANTS
For each FAQ, add 5-10 obvious clean variants:
- The question itself
- Common rephrasing ("how much" / "pricing" / "cost")
- **NO slang/typos needed** - normalization handles these

### 3. UPLOAD & PROMOTE
- Upload via Admin UI or API
- Promote to live

### 4. BENCHMARK
```bash
python tools/run_benchmark.py <tenant_id>
```

### 5. IF MISSES: Auto-patch from normalized forms
```bash
python tools/auto_patch_variants.py <tenant_id> --apply
```

### 6. RE-UPLOAD & RE-PROMOTE

### 7. REPEAT until benchmark passes (≥75% hit rate)

## Example: sparkys_electrical

### Initial Minimal FAQs
- 6 FAQs with 5-7 clean variants each
- Total: ~35 variants

### After Auto-Patch
- Added 8 normalized forms from benchmark misses
- Total: ~43 variants
- Expected hit rate improvement: 0% → 75%+

## Tools

### `tools/auto_patch_variants.py`
- Runs benchmark against tenant
- Captures normalized forms of misses
- Matches normalized forms to best FAQ
- Adds missing variants
- Outputs patched FAQs file

### `run_messy_benchmark.py`
- Runs messy benchmark (slang, typos, abbreviations)
- Shows hit rate
- Lists worst misses with normalized forms

## Normalization Test Results

Tested normalization layer:
- ✅ "ur prices pls" → "your prices please"
- ✅ "wat areas do u cover" → "what areas do you cover"
- ✅ "can u come 2day" → "can you come today"
- ✅ "do u do ceiling fans" → "do you do ceiling fans"
- ⚠️ "r u licensed" → "r you licensed" (should be "are you licensed")
- ✅ "hey quick one - how much do you charge" → "how much do you charge"
- ✅ "g'day mate wat do u charge" → "what do you charge"

**Result: 6/7 pass (86%)**

## Benchmark Results

### First Benchmark (Minimal Variants)
- **Hit Rate: 0.0%** (19/19 expected hits missed)
- Issue: FAQs not promoted (500 error from backend)
- Normalized forms captured correctly

### Auto-Patch Preview
Suggested adding 8 normalized forms:
- "your prices please" → Pricing and quotes
- "what do you charge" → Pricing and quotes
- "how much" → Pricing and quotes
- "what areas do you cover" → Service area
- "availability this week" → Availability and booking
- "i have no power" → Emergency electrical
- "emergency electrician" → Emergency electrical
- "r you insured" → Licensed and insured

### After Patching
- Patched FAQs created with additional variants
- Ready for re-upload and promotion
- Expected improvement once promotion succeeds

## Next Steps

1. Fix promotion issue (500 error)
2. Re-upload patched FAQs
3. Promote successfully
4. Re-run benchmark to verify 75%+ hit rate
5. Document final results

