# MotionMade FAQ System – Operator Manual (Tenant Onboarding + Updates)

## What this system is
- One backend (Render FastAPI + Neon Postgres) serves many businesses (“tenants”).
- Each tenant has its own FAQs and variant profile.
- A pipeline generates variants, uploads them, runs a suite, and rolls back on failure.

## Tenant folder contract (do not break this)
For tenant `<id>` these must exist:
- `tenants/<id>/faqs.json` (your source FAQs)
- `tenants/<id>/variant_profile.json` (must-variants and tuning)
- `tenants/<id>/faqs_variants.json` (generated/working file uploaded to API)
- `tenants/<id>/last_good_faqs_variants.json` (rollback target)
- `tests/<id>.json` (suite)

## Create a new tenant (scaffold)
From repo root:
1) Create the tenant from the template:
   `.\scaffold_tenant.ps1 -NewTenantId <id> -TemplateTenantId motionmade`

2) Edit these files:
   - `tenants\<id>\faqs.json`  (replace with the new business FAQs)
   - `tenants\<id>\variant_profile.json` (update must-hit mappings/variants)
   - `tests\<id>.json` (replace EDIT ME blocks; include must_contain tokens)

3) Run the pipeline:
   `.\run_faq_pipeline.ps1 -TenantId <id>`

## Update an existing tenant (edit + deploy)
1) Edit tenant FAQs/profile:
   - `tenants\<id>\faqs.json`
   - `tenants\<id>\variant_profile.json`

2) Copy source into working file (only if you want to reset working file):
   `Copy-Item .\tenants\<id>\faqs.json .\tenants\<id>\faqs_variants.json -Force`

3) Run:
   `.\run_faq_pipeline.ps1 -TenantId <id>`

## What the pipeline does (guarantees)
Order is always:
1) Backup current `faqs_variants.json` into `tenants/<id>/backups/`
2) Apply core variant library + tenant profile
3) Patch must-hit variants
4) Upload to `/api/v2/admin/tenant/<id>/faqs`
5) Run suite from `tests/<id>.json`
6) If FAIL → re-upload `last_good_faqs_variants.json` and stop
7) If PASS → promote `faqs_variants.json` to `last_good_faqs_variants.json`

## Debugging rules (fast)
- If suite FAILS: fix `faqs.json`, `variant_profile.json`, or `tests/<id>.json` then rerun.
- Never “guess” what’s live. Verify headers:
  - Render: `curl.exe -i --http1.1 https://motionmade-fastapi.onrender.com/api/health`
  - Public: `curl.exe -i --http1.1 https://api.motionmadebne.com.au/api/health`

## Safety rules (do not skip)
- Never commit `.env`
- Do not edit Cloudflare unless routing is broken (prove via /api/health headers first)
