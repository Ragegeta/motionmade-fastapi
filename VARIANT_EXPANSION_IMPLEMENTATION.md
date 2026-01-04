# Variant Expansion Implementation

## Overview

Implemented automated variant expansion system that generates additional FAQ variants using deterministic templates and transformations. This improves robustness without lowering the THETA threshold (0.82).

## Changes Made

### 1. Created `tools/expand_variants.py`

**Features:**
- Question starter/ender templates (e.g., "what is", "how much", "do you", "can you")
- Slang replacements (u/ur/pls/wat/etc)
- Key-term short forms (pricing/price, cleaning/clean, etc.)
- Hard cap: max 30 variants per FAQ
- Deduplication and normalization
- Preserves existing variants (must_variants still win)

**Usage:**
```bash
python tools/expand_variants.py \
  --input tenants/<tenantId>/faqs.json \
  --output tenants/<tenantId>/faqs_expanded.json \
  --overwrite
```

**Example Output:**
- Input: 20 FAQs with 8 total variants (0.4 avg per FAQ)
- Output: 20 FAQs with 580 total variants (29.0 avg per FAQ)

### 2. Modified `run_faq_pipeline.ps1`

**Added Parameter:**
```powershell
[switch]$ExpandVariants = $false  # Enable automated variant expansion
```

**Integration:**
- If `-ExpandVariants` is enabled, runs `expand_variants.py` before pipeline
- Generates `faqs_expanded.json` from `faqs.json`
- Uses expanded file as source for variant library application
- Existing must_variants patching logic remains unchanged

**Pipeline Flow:**
1. (Optional) Expand variants → `faqs_expanded.json`
2. Copy source (`faqs.json` or `faqs_expanded.json`) → `faqs_variants.json`
3. Apply variant library (core + tenant profile)
4. Patch must-hit variants
5. Patch parking variants
6. Upload to server
7. Run suite tests

### 3. Created `verify_variant_expansion.ps1`

Verification script that:
- Runs baseline pipeline (no expansion) + benchmark
- Runs expanded pipeline (with expansion) + benchmark
- Compares hit/clarify/fallback rates
- Verifies THETA = 0.82 unchanged

## Verification Steps

### Prerequisites
```bash
# Install Python dependencies (if needed)
pip install requests

# Ensure you have ADMIN_TOKEN in .env
```

### Step 1: Baseline (No Expansion)
```powershell
cd C:\MM\motionmade-fastapi

# Run pipeline without expansion
.\run_faq_pipeline.ps1 `
  -TenantId biz9_real `
  -AdminBase https://motionmade-fastapi.onrender.com `
  -PublicBase https://api.motionmadebne.com.au `
  -Origin https://motionmadebne.com.au

# Run benchmark
python tools/bench_messy_inputs.py `
  --base-url https://api.motionmadebne.com.au `
  --tenant-id biz9_real `
  --output-dir tools
```

### Step 2: Expanded (With Expansion)
```powershell
# Run pipeline with expansion
.\run_faq_pipeline.ps1 `
  -TenantId biz9_real `
  -AdminBase https://motionmade-fastapi.onrender.com `
  -PublicBase https://api.motionmadebne.com.au `
  -Origin https://motionmadebne.com.au `
  -ExpandVariants

# Run benchmark
python tools/bench_messy_inputs.py `
  --base-url https://api.motionmadebne.com.au `
  --tenant-id biz9_real `
  --output-dir tools
```

### Step 3: Compare Results

Expected improvements:
- **Hit Rate**: Should increase (more variants = more matches)
- **Clarify Rate**: Should remain similar or decrease slightly
- **Fallback Rate**: Should decrease (fewer misses)
- **THETA**: Unchanged at 0.82 (strict matching preserved)

## Example Expansion

**Input FAQ:**
```json
{
  "question": "Oven clean add-on",
  "answer": "Yes - oven cleaning is an optional add-on and costs $89."
}
```

**Expanded Variants (sample):**
- "Oven clean add-on?"
- "what is Oven clean add-on"
- "do you Oven clean add-on"
- "can you Oven clean add-on"
- "Oven clean add-on pls"
- "what's Oven clean add-on please"
- "how much Oven clean add-on"
- ... (up to 30 total variants)

## Safety Features

1. **Hard Cap**: Max 30 variants per FAQ (prevents file size explosion)
2. **Deduplication**: Normalized deduplication prevents duplicates
3. **Preserves Originals**: Original question and existing variants are prioritized
4. **THETA Unchanged**: Matching threshold remains 0.82 (strict)
5. **Deterministic**: Same input always produces same output

## Files Changed

- `tools/expand_variants.py` (NEW)
- `run_faq_pipeline.ps1` (MODIFIED)
- `verify_variant_expansion.ps1` (NEW)

## Testing

To verify the implementation works correctly:

1. **Test expansion script:**
   ```bash
   python tools/expand_variants.py \
     --input tenants/biz9_real/faqs.json \
     --output tenants/biz9_real/faqs_expanded_test.json \
     --overwrite
   ```

2. **Verify output:**
   - Check that variants are generated
   - Check that cap is respected (max 30 per FAQ)
   - Check that deduplication works

3. **Run full verification:**
   ```powershell
   .\verify_variant_expansion.ps1 -TenantId biz9_real
   ```

## Notes

- Expansion is **offline** (runs during pipeline, not at query time)
- Expansion is **deterministic** (same input = same output)
- Expansion is **optional** (default: disabled, use `-ExpandVariants` to enable)
- Existing must_variants from profile still take precedence
- THETA threshold (0.82) is **not** lowered - matching remains strict


