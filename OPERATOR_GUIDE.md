# Final Onboarding Solution

## One URL for Everything

**Admin Dashboard:** https://motionmade-fastapi.onrender.com/admin

## Operator Flow (3 Steps)

1. **Go to Admin UI** â†’ Click "Onboarding"
2. **Follow 7-step wizard:**
   - Select tenant
   - Add domains
   - Upload FAQs
   - Promote (auto-expands variants)
   - Run benchmark
   - Sync Worker domains
   - Copy install snippet
3. **Done!** Tenant is ready.

## What's Automatic

- âœ… Variant expansion (during promote)
- âœ… Suite gate (during promote)
- âœ… Benchmark gate (one-click)
- âœ… Worker domain routing (one-click or manual)

## Command Line Alternative

`powershell
.\tools\onboard_tenant.ps1 
    -TenantId "acme_clean" 
    -Domains @("acmecleaning.com.au") 
    -FaqPath "tenants\acme_clean\faqs.json" 
    -AdminBase "https://motionmade-fastapi.onrender.com"
`

## URLs Reference

- **Admin UI**: https://motionmade-fastapi.onrender.com/admin
- **Public API**: https://api.motionmadebne.com.au
- **Widget JS**: https://mm-client1-creator-ui.pages.dev/widget.js
