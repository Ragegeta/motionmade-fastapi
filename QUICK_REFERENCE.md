# Quick Reference

## URLs

| Service | URL |
|---------|-----|
| API (public) | https://api.motionmadebne.com.au |
| API (Render direct) | https://motionmade-fastapi.onrender.com |
| Worker | https://mm-client1-creator-backend-v1-0-0.abbedakbery14.workers.dev |
| Widget JS | https://mm-client1-creator-ui.pages.dev/widget.js |
| Admin UI | https://motionmade-fastapi.onrender.com/admin |

## How to Onboard a Tenant (3 Steps)

### Option 1: Admin UI (Recommended)

1. **Go to Admin UI**: https://motionmade-fastapi.onrender.com/admin
2. **Click "Onboarding"** tab
3. **Follow the steps:**
   - Select/Create tenant
   - Add domain(s)
   - Paste/upload FAQ JSON to staging
   - Click "Promote" (runs suite + auto-expands variants)
   - Click "Run Benchmark" (verifies quality)
   - Click "Sync Worker Domains" (enables widget routing)
   - Check readiness and copy install snippet

### Option 2: Command Line

```powershell
.\tools\onboard_tenant.ps1 `
    -TenantId "acme_clean" `
    -Domains @("acmecleaning.com.au") `
    -FaqPath "tenants\acme_clean\faqs.json" `
    -AdminBase "https://motionmade-fastapi.onrender.com" `
    -WorkerDbName "motionmade_creator_enquiries" `
    -WorkerBackendPath "C:\MM\10__CLIENTS\client1\backend"
```

**Note:** Variant expansion happens automatically during promote. No manual step needed.

## Key Endpoints

### Public (no auth)

#### Widget Chat (via Worker)
```
POST /api/v2/widget/chat
Headers:
  Content-Type: application/json
  Origin: https://customer-domain.com
Body: {"message": "user question"}
```

#### Generate Quote Reply (direct API)
```
POST /api/v2/generate-quote-reply
Headers:
  Content-Type: application/json
Body: {
  "tenantId": "biz9_real",
  "customerMessage": "user question"
}
```

#### Health Check
```
GET /api/health
```

#### Admin API Health Check
```
GET /admin/api/health
```
Returns route verification status.

### Admin (requires `Authorization: Bearer {ADMIN_TOKEN}`)

#### List Tenants
```
GET /admin/api/tenants
```

#### Get Tenant Detail
```
GET /admin/api/tenant/{tenantId}
```

#### Add Domain
```
POST /admin/api/tenant/{tenantId}/domains
Body: {"domain": "example.com"}
```

#### Upload Staged FAQs
```
PUT /admin/api/tenant/{tenantId}/faqs/staged
Body: [{"question": "Q", "answer": "A", "variants": ["v1"]}]
```

#### Promote Staged FAQs
```
POST /admin/api/tenant/{tenantId}/promote
```

#### Rollback to Last Good
```
POST /admin/api/tenant/{tenantId}/rollback
```

#### Get Stats (last 24h)
```
GET /admin/api/tenant/{tenantId}/stats
```

#### Get Alerts (last hour)
```
GET /admin/api/tenant/{tenantId}/alerts
```

#### Get Readiness
```
GET /admin/api/tenant/{tenantId}/readiness
```

#### Run Benchmark
```
POST /admin/api/tenant/{tenantId}/benchmark
```
Runs messy benchmark suite and returns results with worst misses.

#### Sync Worker Domains
```
POST /admin/api/tenant/{tenantId}/domains/sync-worker
```
Syncs tenant domains from FastAPI DB to Worker D1 database (requires Cloudflare API config).

### Alternative Admin Paths (Cloudflare-compatible)

All `/admin/api/...` endpoints also available at `/api/v2/admin/...`:
- `/api/v2/admin/tenant/{tenantId}/stats`
- `/api/v2/admin/tenant/{tenantId}/alerts`
- `/api/v2/admin/tenant/{tenantId}/readiness`

## Widget Installation

### Basic
```html
<script src="https://mm-client1-creator-ui.pages.dev/widget.js"></script>
```

### With Customization
```html
<script 
  src="https://mm-client1-creator-ui.pages.dev/widget.js"
  data-api="https://api.motionmadebne.com.au"
  data-greeting="Hi! How can I help you today?"
  data-header="Chat with us"
  data-color="#2563eb"
  data-position="bottom-right">
</script>
```

### Configuration Options

| Attribute | Default | Description |
|-----------|---------|-------------|
| `data-api` | `https://api.motionmadebne.com.au` | Base API URL |
| `data-greeting` | `"Hi! How can I help you today?"` | Initial greeting message |
| `data-header` | `"Chat with us"` | Chat window header text |
| `data-color` | `"#2563eb"` | Primary color (hex) |
| `data-position` | `"bottom-right"` | Widget position: `bottom-right`, `bottom-left`, `top-right`, `top-left` |

## Database Tables

### `tenants`
- `id` (TEXT PRIMARY KEY)
- `name` (TEXT)
- `created_at` (TIMESTAMPTZ)

### `tenant_domains`
- `id` (BIGSERIAL PRIMARY KEY)
- `tenant_id` (TEXT, FK to tenants)
- `domain` (TEXT)
- `enabled` (BOOLEAN)
- `created_at` (TIMESTAMPTZ)

### `faq_items`
- `id` (BIGSERIAL PRIMARY KEY)
- `tenant_id` (TEXT)
- `question` (TEXT)
- `answer` (TEXT)
- `embedding` (vector(1536))
- `enabled` (BOOLEAN)
- `is_staged` (BOOLEAN)
- `updated_at` (TIMESTAMPTZ)

### `faq_items_last_good`
- Same structure as `faq_items` (no `is_staged` column)
- Used for rollback

### `telemetry`
- `id` (BIGSERIAL PRIMARY KEY)
- `tenant_id` (TEXT)
- `created_at` (TIMESTAMPTZ)
- `query_length` (INTEGER)
- `normalized_length` (INTEGER)
- `query_hash` (TEXT)
- `normalized_hash` (TEXT)
- `intent_count` (INTEGER)
- `debug_branch` (TEXT)
- `faq_hit` (BOOLEAN)
- `top_faq_id` (BIGINT)
- `retrieval_score` (REAL)
- `rewrite_triggered` (BOOLEAN)
- `latency_ms` (INTEGER)

## Debug Branches

| Branch | Meaning |
|--------|---------|
| `clarify` | Input was junk/too short → ask user to rephrase |
| `fact_hit` | FAQ matched with high confidence |
| `fact_rewrite_hit` | FAQ matched after rewrite |
| `fact_miss` | FAQ retrieval failed → use LLM |
| `general_ok` | LLM generated safe response |
| `general_fallback` | LLM response violated safety → use fallback |
| `error` | System error occurred |

## Common Tasks

### Onboard New Tenant (Admin UI - Recommended)

1. Go to: https://motionmade-fastapi.onrender.com/admin
2. Click "Onboarding" tab
3. Follow the 7-step wizard:
   - Select/Create tenant
   - Add domain(s)
   - Upload FAQ JSON to staging
   - Promote (runs suite + auto-expands variants)
   - Run benchmark (verifies quality)
   - Sync Worker domains (enables widget routing)
   - Check readiness and copy install snippet

### Onboard New Tenant (API/CLI)

1. Create tenant: `POST /admin/api/tenants` with `{"id": "new_tenant", "name": "New Tenant"}`
2. Add domain: `POST /admin/api/tenant/new_tenant/domains` with `{"domain": "example.com"}`
3. Upload FAQs: `PUT /admin/api/tenant/new_tenant/faqs/staged`
4. Promote: `POST /admin/api/tenant/new_tenant/promote` (auto-expands variants, runs suite)
5. Run benchmark: `POST /admin/api/tenant/new_tenant/benchmark`
6. Sync Worker: `POST /admin/api/tenant/new_tenant/domains/sync-worker`
7. Check readiness: `GET /admin/api/tenant/new_tenant/readiness`
8. Get install snippet from Admin UI

### Update FAQs
1. Upload new FAQs to staging: `PUT /admin/api/tenant/{id}/faqs/staged`
2. Promote: `POST /admin/api/tenant/{id}/promote`
3. If tests fail, rollback: `POST /admin/api/tenant/{id}/rollback`

### Monitor Tenant Health
1. Check stats: `GET /admin/api/tenant/{id}/stats`
2. Check alerts: `GET /admin/api/tenant/{id}/alerts`
3. Review fallback rate - if >40%, add FAQ variants

### Run Production Confidence Pack
The confidence pack tests repeatability, scale, and adversarial scenarios with 80+ questions.

**Basic run (5 iterations):**
```powershell
.\tools\run_confidence_pack.ps1 -TenantId "sparkys_electrical"
```

**Scale test (100 FAQs):**
```powershell
.\tools\run_confidence_pack.ps1 -TenantId "sparkys_electrical" -ScaleTest
```

**Custom runs:**
```powershell
.\tools\run_confidence_pack.ps1 -TenantId "sparkys_electrical" -Runs 10
```

**Custom test pack:**
```powershell
.\tools\run_confidence_pack.ps1 -TenantId "sparkys_electrical" -TestPackPath "tools\testpacks\custom_pack.json"
```

The script:
- Runs the test pack N times (default 5)
- Reports mean/min/max hit rates, wrong-hit rates, latency (P50/P95)
- Tests repeatability (variance <= 5 percentage points)
- Optionally scales to 100 FAQs to test with larger candidate sets
- Saves detailed results to `tools/results/confidence_{tenant}_{timestamp}.json`

**Pass/Fail Gates:**
- Hit rate (should-hit) >= 85%
- Wrong-hit rate (should-miss) = 0%
- Edge clarify rate >= 70%
- Repeatability variance <= 5pp
- Latency P50 <= 2.5s, P95 <= 6s

Results include per-question traces with retrieval scores, branches, and failure analysis.

## Troubleshooting

### Widget shows "domain not allowed"
- Check domain is in `tenant_domains` table with `enabled = 1`
- Verify exact domain match (including www if used)

### Low FAQ hit rate
- Add more FAQ variants for common phrasings
- Check retrieval scores in telemetry
- Consider rewrite threshold tuning

### High latency
- Check database connection pool
- Review embedding generation time
- Check LLM API response times

### Admin endpoints return 401
- Verify `ADMIN_TOKEN` is set correctly
- Check `Authorization: Bearer {token}` header format


