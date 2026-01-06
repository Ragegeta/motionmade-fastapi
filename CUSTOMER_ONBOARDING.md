# Customer Onboarding Checklist

## Pre-Onboarding Discovery Call

### Information to Gather
- [ ] Business name and industry
- [ ] Primary service offerings
- [ ] Service area/coverage
- [ ] Common customer questions (top 10-20)
- [ ] Pricing structure
- [ ] Booking process
- [ ] Contact information (phone, email)
- [ ] Brand colors/preferences
- [ ] Domain(s) where widget will be installed

### Questions to Ask
1. What are the most common questions customers ask?
2. How do customers typically phrase questions? (formal vs casual)
3. What information do customers need before booking?
4. Are there any seasonal or time-sensitive services?
5. What makes your business unique?

## Onboarding Steps

### 1. Quick Start
```powershell
.\quick_onboard.ps1 -TenantId "customer_id" -Domain "customer-domain.com" -BusinessName "Customer Business Name"
```

This creates:
- Tenant directory structure
- Starter FAQ template
- Next steps instructions

### 2. Customize FAQs
- [ ] Edit `tenants/{tenant_id}/faqs.json`
- [ ] Replace placeholder text with real business information
- [ ] Add all common questions and answers
- [ ] Include variants (slang, typos, different phrasings)
- [ ] Test with real customer language

### 3. Add Domain via Admin UI
- [ ] Navigate to: https://motionmade-fastapi.onrender.com/admin
- [ ] Add tenant: `{tenant_id}`
- [ ] Add domain: `customer-domain.com`
- [ ] Verify domain is enabled

### 4. Upload and Promote
```powershell
# Upload staged FAQs
$body = Get-Content 'tenants/{tenant_id}/faqs.json' -Raw
Invoke-RestMethod -Uri 'https://motionmade-fastapi.onrender.com/admin/api/tenant/{tenant_id}/faqs/staged' `
    -Method PUT -Headers @{"Authorization"="Bearer $token"; "Content-Type"="application/json"} -Body $body

# Promote to live (runs test suite)
Invoke-RestMethod -Uri 'https://motionmade-fastapi.onrender.com/admin/api/tenant/{tenant_id}/promote' `
    -Method POST -Headers @{"Authorization"="Bearer $token"}
```

### 5. Run Benchmark
```powershell
python tools/run_benchmark.py {tenant_id}
```

**Thresholds:**
- ✅ FAQ hit rate >= 75%
- ✅ Fallback rate == 0% (for non-junk queries)
- ✅ At least 15 test cases

### 6. Generate Install Snippet
Get from Admin UI or use:
```html
<script 
  src="https://mm-client1-creator-ui.pages.dev/widget.js"
  data-greeting="Hi! How can I help?"
  data-header="Business Name"
  data-color="#2563eb"
></script>
```

### 7. Customer Installation
- [ ] Send install snippet to customer
- [ ] Provide installation instructions (paste before `</body>`)
- [ ] Mention CSP requirements if needed
- [ ] Test widget appears and responds correctly
- [ ] Verify domain routing works

## Post-Launch (Day 1-3)

### Day 1: Initial Check
- [ ] Check telemetry for actual queries
  - Review `/admin/api/tenant/{id}/stats`
  - Look for unexpected patterns
- [ ] Review any fallbacks
  - Check `/admin/api/tenant/{id}/alerts`
  - Identify queries that didn't hit FAQs
- [ ] Test widget on customer site
  - Verify appearance
  - Test a few queries
  - Check mobile responsiveness

### Day 2-3: Optimization
- [ ] Add variants for common misses
  - Review telemetry for missed queries
  - Add variants to relevant FAQs
  - Re-upload and promote
- [ ] Check customer satisfaction
  - Ask customer for feedback
  - Review any complaints or issues
  - Adjust answers if needed

### Ongoing Monitoring
- [ ] Weekly review of stats and alerts
- [ ] Monthly review of FAQ coverage
- [ ] Quarterly optimization based on query patterns

## Pricing Notes

### Setup Fee
- **Amount:** $___
- **Includes:** Initial FAQ setup, domain configuration, testing

### Monthly Fee
- **Amount:** $___
- **Includes:** 
  - Up to ___ queries/month
  - FAQ updates
  - Basic support

### Overage Rate
- **Amount:** $___ per query over included limit
- **Billing:** Monthly, prorated

### Additional Services
- FAQ expansion: $___
- Custom styling: $___
- Priority support: $___

## Troubleshooting

### Widget Not Appearing
- [ ] Check script tag is before `</body>`
- [ ] Verify domain is registered and enabled
- [ ] Check browser console for errors
- [ ] Verify CSP allows widget.js and API domain

### Queries Not Hitting FAQs
- [ ] Review benchmark results
- [ ] Add more variants to FAQs
- [ ] Check normalization is working
- [ ] Review telemetry for actual query patterns

### Domain Not Allowed Error
- [ ] Verify domain in Admin UI
- [ ] Check domain is enabled
- [ ] Ensure exact match (including https://)
- [ ] Check Worker D1 database

## Resources

- Admin UI: https://motionmade-fastapi.onrender.com/admin
- API Health: https://api.motionmadebne.com.au/api/health
- Widget URL: https://mm-client1-creator-ui.pages.dev/widget.js
- Documentation: See `V1_LAUNCH_CHECKLIST.md` for technical details


