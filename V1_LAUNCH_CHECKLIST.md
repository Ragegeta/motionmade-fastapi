# V1 Launch Checklist

## Pre-Launch (One-Time Setup)

- [ ] FastAPI backend deployed to Render
- [ ] Cloudflare Worker deployed
- [ ] Widget.js deployed to Cloudflare Pages
- [ ] Database schema migrated (telemetry, staging tables)
- [ ] Admin token set in environment variables

## Per-Tenant Onboarding

### Prerequisites
- [ ] Tenant record created via Admin UI or API
- [ ] Domain(s) registered in `tenant_domains` table (with `enabled = 1`)
- [ ] FAQ JSON prepared at `tenants/{tenant_id}/faqs.json`
- [ ] Test suite created at `tests/{tenant_id}.json`

### Single Command Onboarding

Run the automated onboarding script (handles everything):

```powershell
.\new_tenant_onboard.ps1 `
  -TenantId acme_cleaning `
  -AdminBase https://motionmade-fastapi.onrender.com `
  -PublicBase https://api.motionmadebne.com.au `
  -Origin https://example.com
```

**What it does:**
1. ✅ **Variant Expansion**: Automatically expands FAQ variants (mandatory)
2. ✅ **Pipeline**: Runs full FAQ pipeline (apply library, patch variants, upload)
3. ✅ **Suite Tests**: Runs tenant test suite (must pass)
4. ✅ **Benchmark Gate**: Runs benchmark with thresholds:
   - FAQ hit rate >= 70%
   - Non-junk fallback rate == 0%
   - At least 15 test cases
5. ✅ **Promotion**: Promotes to `last_good` if all gates pass

**If onboarding fails:**
- Review benchmark results
- Add more FAQ variants or improve coverage
- Fix any suite test failures
- Re-run the onboarding script

### Post-Onboarding Steps

### 1. Readiness Check
- [ ] Call `GET /admin/api/tenant/{id}/readiness`
- [ ] Verify all checks pass
- [ ] Address any warnings

### 2. Generate Install Snippet
- [ ] Get snippet from Admin UI "Install" section
- [ ] Customize `data-greeting`, `data-header`, `data-color` if needed
- [ ] Send to customer with installation instructions

### 3. Customer Installation
- [ ] Customer adds `<script>` to their site
- [ ] Test widget appears and responds correctly
- [ ] Verify domain routing works (no "domain not allowed" error)

### 4. Go-Live Verification
- [ ] Send test messages through live widget
- [ ] Check telemetry shows requests
- [ ] Verify hit rate is acceptable (>70% from benchmark gate)

## Ongoing Monitoring

- [ ] Check `/admin/api/tenant/{id}/stats` periodically
- [ ] Monitor `/admin/api/tenant/{id}/alerts` for warnings
- [ ] Review fallback rate - add FAQ variants if too high

## Rollback Procedure

If something breaks after a FAQ update:
```bash
POST /admin/api/tenant/{id}/rollback
```

This restores the last known-good FAQ set.

## Support Contacts

- Technical issues: [your email]
- FAQ updates: Use Admin UI or API

