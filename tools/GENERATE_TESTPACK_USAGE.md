# generate_testpack.py Usage Guide

## Overview

The `generate_testpack.py` script generates JSON test packs for tenant confidence testing. It creates diverse queries across multiple patterns (short keywords, normal sentences, messy speech, typos, Aussie phrasing, emergency phrases, pricing intent, and wrong-service should-miss queries).

## Quick Start

### Generate a test pack:

```powershell
cd motionmade-fastapi
python tools/generate_testpack.py --tenant sparkys_electrical --out tools/testpacks/generated_sparkys.json --seed 123
```

**Output:**
```
Generated test pack: tools/testpacks/generated_sparkys.json
  Tenant: sparkys_electrical
  Seed: 123
  Total queries: 172
    should_hit: 108
    should_miss: 54
    edge_unclear: 10
```

### Use the generated test pack with run_confidence_pack.ps1:

```powershell
.\tools\run_confidence_pack.ps1 `
    -TenantId "sparkys_electrical" `
    -Runs 10 `
    -AdminBase "https://motionmade-fastapi.onrender.com" `
    -PublicBase "https://motionmade-fastapi.onrender.com" `
    -TestPackPath ".\tools\testpacks\generated_sparkys.json" `
    -DebugTimings
```

## Command Line Options

- `--tenant` (required): Tenant ID (e.g., `sparkys_electrical`)
- `--out` (required): Output JSON file path
- `--seed` (optional): Random seed for reproducibility (default: 123)

## Examples

### Generate a test pack with default seed:
```powershell
python tools/generate_testpack.py --tenant sparkys_electrical --out tools/testpacks/generated_sparkys.json
```

### Generate a test pack with custom seed:
```powershell
python tools/generate_testpack.py --tenant sparkys_electrical --out tools/testpacks/generated_sparkys_seed456.json --seed 456
```

### Generate for different tenant:
```powershell
python tools/generate_testpack.py --tenant another_tenant --out tools/testpacks/generated_another.json --seed 123
```

## Generated Query Categories

The script generates queries across these patterns:

1. **Short keywords (2-3 words)**: e.g., "powerpoint broken", "smoke alarm beeping"
2. **Normal sentences**: e.g., "my powerpoint stopped working can you fix it"
3. **Messy speech**: e.g., "um my powerpoint like stopped working"
4. **Typos**: e.g., "powerpont brokn" (letter swaps, missing vowels)
5. **Aussie phrasing**: e.g., "power point", "safety switch", "RCD", "GPO"
6. **Emergency phrasing**: e.g., "sparks coming from outlet", "burning smell"
7. **Pricing intent**: e.g., "how much for ceiling fan install", "callout fee"
8. **Wrong-service should-miss**: plumbing, locksmith, HVAC, solar, etc.

## Output Format

The generated JSON matches the existing test pack structure:

```json
{
  "name": "Sparkys_Electrical Generated Test Pack",
  "description": "Generated test pack with 172 queries (seed=123)",
  "should_hit": [...],
  "should_miss": [...],
  "edge_unclear": [...]
}
```

## Running Tests

Run the unit tests to verify the generator:

```powershell
python -m pytest tests/test_generate_testpack.py -v
```

## Integration with run_confidence_pack.ps1

The generated test pack can be used directly with the confidence pack script:

1. **Generate the test pack:**
   ```powershell
   python tools/generate_testpack.py --tenant sparkys_electrical --out tools/testpacks/generated_sparkys.json --seed 123
   ```

2. **Run confidence pack with the generated test pack:**
   ```powershell
   .\tools\run_confidence_pack.ps1 `
       -TenantId "sparkys_electrical" `
       -Runs 5 `
       -TestPackPath ".\tools\testpacks\generated_sparkys.json" `
       -DebugTimings
   ```

3. **The script will:**
   - Load the test pack from the specified path
   - Run all queries from `should_hit`, `should_miss`, and `edge_unclear`
   - Log per-request details to console
   - Write results to `tools/results/confidence_{tenant}_{timestamp}.json`

## Reproducibility

Using the same `--seed` value produces the same queries. This ensures:
- Consistent test results across runs
- Ability to regenerate exact test packs
- Easy debugging by reproducing specific query sets

Example:
```powershell
# These produce identical output
python tools/generate_testpack.py --tenant sparkys_electrical --out pack1.json --seed 123
python tools/generate_testpack.py --tenant sparkys_electrical --out pack2.json --seed 123
# pack1.json and pack2.json will be identical
```

## Requirements Met

✅ Output format matches existing test pack JSON structure  
✅ Generates at least 120 queries (actually generates 172+)  
✅ Covers all required query buckets  
✅ Reproducible with --seed parameter  
✅ CLI with required arguments  
✅ Unit tests validate structure and counts  
✅ No database or external API dependencies

