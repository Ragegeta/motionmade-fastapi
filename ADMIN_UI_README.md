# Admin UI - Tenant Management

Minimal web UI for self-service tenant onboarding and FAQ management.

## Features

- **Tenant Management**: Create tenants, view list
- **Domain Management**: Add/remove allowed domains per tenant
- **FAQ Upload**: Upload FAQs via JSON (replaces existing FAQs)
- **Stats Dashboard**: View hit/clarify/fallback/rewrite rates and latency (last 24 hours)
- **Simple Auth**: Admin token login (same `ADMIN_TOKEN` as API)

## Running Locally

1. **Start the FastAPI server**:
   ```powershell
   cd C:\MM\motionmade-fastapi
   .\.venv\Scripts\Activate.ps1
   python -m uvicorn app.main:app --reload --port 8000
   ```

2. **Open the admin UI**:
   - Navigate to: `http://localhost:8000/admin`
   - Enter your `ADMIN_TOKEN` (from `.env` file)
   - Click "Login"

3. **Use the UI**:
   - Click "+ New Tenant" to create a tenant
   - Click "View" on any tenant to manage domains, upload FAQs, view stats
   - Upload FAQs as JSON array: `[{"question": "Q", "answer": "A", "variants": ["v1"]}]`

## API Endpoints

All admin endpoints require `Authorization: Bearer <ADMIN_TOKEN>` header.

### Tenant Management
- `GET /admin/api/tenants` - List all tenants
- `POST /admin/api/tenants` - Create tenant (`{"id": "tenant_id", "name": "Tenant Name"}`)
- `GET /admin/api/tenant/{tenantId}` - Get tenant details + domains

### Domain Management
- `POST /admin/api/tenant/{tenantId}/domains` - Add domain (`{"domain": "example.com"}`)
- `DELETE /admin/api/tenant/{tenantId}/domains/{domain}` - Remove domain

### FAQ Management
- `PUT /admin/tenant/{tenantId}/faqs` - Upload FAQs (replaces existing)
- `PUT /admin/api/tenant/{tenantId}/faqs/staged` - Stage FAQs (MVP: placeholder)

### Stats
- `GET /admin/api/tenant/{tenantId}/stats` - Get telemetry stats (last 24 hours)

### Actions (Placeholder)
- `POST /admin/api/tenant/{tenantId}/promote` - Promote staged FAQs (MVP: use pipeline script)
- `POST /admin/api/tenant/{tenantId}/rollback` - Rollback to last_good (MVP: use pipeline script)

## Suite Runs & Promote/Rollback

For suite runs and promote/rollback operations, use the pipeline script:

```powershell
.\run_faq_pipeline.ps1 -TenantId <tenant_id>
```

The pipeline automatically:
- Uploads FAQs
- Runs test suite
- Rolls back on failure
- Promotes on success

## Database Schema

The admin UI uses these tables:
- `tenants` - Tenant metadata
- `tenant_domains` - Allowed domains per tenant
- `faq_items` - FAQ questions/answers
- `faq_variants` - FAQ variant embeddings
- `telemetry` - Request telemetry (privacy-safe)

## Notes

- Admin operations use Render base URL (not Cloudflare routing)
- No raw customer text is stored (only lengths + hashes)
- Widget endpoints are not modified
- All changes are minimal and test-covered







