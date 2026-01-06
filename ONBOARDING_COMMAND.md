# One Command for Future Businesses

## Standardized Onboarding Command

```powershell
.\tools\onboard_tenant.ps1 `
    -TenantId "acme_clean" `
    -Domains @("acmecleaning.com.au") `
    -FaqPath "tenants\acme_clean\faqs.json" `
    -AdminBase "https://motionmade-fastapi.onrender.com" `
    -WorkerDbName "motionmade_creator_enquiries" `
    -WorkerBackendPath "C:\MM\10__CLIENTS\client1\backend"
```

## What It Does Automatically

1. ✅ Uploads FAQs to staging
2. ✅ Auto-expands variants (during promote)
3. ✅ Runs suite gate (must pass)
4. ✅ Runs benchmark gate (>=75% hit, 0% fallback, 0% wrong hits)
5. ✅ Adds domain(s) to Worker D1 for widget routing
6. ✅ Generates install snippet

## Example with Custom Branding

```powershell
.\tools\onboard_tenant.ps1 `
    -TenantId "acme_clean" `
    -Domains @("acmecleaning.com.au") `
    -FaqPath "tenants\acme_clean\faqs.json" `
    -BusinessName "Acme Cleaning Services" `
    -PrimaryColor "#2563eb" `
    -Greeting "Hi! How can we help?"
```

## Parameters

- `-TenantId` (required): Tenant identifier
- `-Domains` (required): Array of domains for widget routing
- `-FaqPath` (required): Path to FAQs JSON file
- `-AdminBase` (optional): Admin API base URL (default: Render)
- `-WorkerDbName` (optional): Worker D1 database name
- `-WorkerBackendPath` (optional): Path to Worker backend for wrangler
- `-BusinessName` (optional): Display name for widget
- `-PrimaryColor` (optional): Widget color (default: #2563eb)
- `-Greeting` (optional): Widget greeting message
- `-SkipBenchmark` (switch): Skip benchmark gate
- `-SkipWorkerDomain` (switch): Skip Worker domain setup

## Notes

- Variant expansion happens automatically during promote (no manual step)
- Benchmark gate enforces quality thresholds (fails if not met)
- Worker domain setup requires wrangler CLI and backend path
- Script handles 404 routes gracefully with fallbacks


