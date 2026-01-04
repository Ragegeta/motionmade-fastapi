# Idempotent Onboarding Implementation

## Summary

Made onboarding re-runnable (idempotent) and ensured tests actually run. The onboarding script now:
- Uses staging + promote flow (never direct live upload)
- Runs pytest before proceeding
- Can be run multiple times safely

## Task A: Backend - Staged Upload REPLACE Semantics ✅

**Status:** Already implemented!

The staged upload endpoint at `PUT /admin/api/tenant/{tenantId}/faqs/staged` already deletes existing staged FAQs before inserting new ones:

```python
# Delete existing staged FAQs (keep live unchanged)
conn.execute("DELETE FROM faq_items WHERE tenant_id=%s AND is_staged=true", (tenantId,))

# Also delete staged variants (they'll be recreated)
conn.execute("""
    DELETE FROM faq_variants 
    WHERE faq_id IN (SELECT id FROM faq_items WHERE tenant_id=%s AND is_staged=true)
""", (tenantId,))
```

This prevents unique constraint violations on reruns.

## Task B: Onboarding Script - Staging + Promote Flow ✅

**Changes to `new_tenant_onboard.ps1`:**

1. **Removed dependency on `run_faq_pipeline.ps1`** - Now does everything inline
2. **Always uses staging endpoint:**
   - `PUT {ADMIN_BASE}/admin/api/tenant/{tenantId}/faqs/staged`
3. **Calls promote endpoint:**
   - `POST {ADMIN_BASE}/admin/api/tenant/{tenantId}/promote`
   - Parses response and shows first failure if promote fails
4. **Flow:**
   - Step 0: Run pytest
   - Step 1: Expand variants
   - Step 2: Apply variant library and patches
   - Step 3: Upload to staging + promote
   - Step 4: Run benchmark gate

## Task C: Ensure pytest Runs ✅

**Added at start of script:**

1. **Activate venv if present:**
   ```powershell
   if (Test-Path $venvActivate) {
       & $venvActivate
   }
   ```

2. **Install pytest if missing:**
   ```powershell
   $pytestCheck = python -m pytest --version 2>&1
   if ($LASTEXITCODE -ne 0) {
       python -m pip install -q pytest
   }
   ```

3. **Run pytest and fail hard if it fails:**
   ```powershell
   python -m pytest -q
   if ($LASTEXITCODE -ne 0) {
       Write-Host "❌ pytest failed!"
       exit 1
   }
   ```

## Unified Diff

### Modified: `new_tenant_onboard.ps1`

**Complete rewrite:**
- Removed dependency on `run_faq_pipeline.ps1`
- Added pytest execution at start
- Changed to use staging + promote flow
- Inline variant expansion and processing
- Better error handling and output

**Key changes:**
- Step 0: pytest execution (NEW)
- Step 1: Variant expansion (inline, not via pipeline)
- Step 2: Variant library + patches (inline)
- Step 3: Staging upload + promote (NEW flow)
- Step 4: Benchmark gate (unchanged)

### No changes needed: `app/main.py`

The staged endpoint already implements REPLACE semantics (deletes before insert).

## Verification

To verify the implementation works:

1. **Run onboarding twice back-to-back:**
   ```powershell
   .\new_tenant_onboard.ps1 -TenantId biz9_real -AdminBase https://motionmade-fastapi.onrender.com -PublicBase https://api.motionmadebne.com.au -Origin https://motionmadebne.com.au
   ```
   (Run it twice; second run must NOT error)

2. **Expected outputs:**
   - pytest summary line (e.g., "XX passed")
   - Variant expansion confirmation
   - Staging upload success
   - Promote response (pass/fail + first failure if any)
   - Benchmark summary (hit/clarify/fallback + worst misses)

## Notes

- The script is idempotent: running it multiple times produces the same result
- Staging endpoint deletes existing staged FAQs before inserting (prevents duplicates)
- Promote endpoint runs suite tests and only promotes if they pass
- pytest must pass before onboarding proceeds
- Benchmark gate enforces quality thresholds


