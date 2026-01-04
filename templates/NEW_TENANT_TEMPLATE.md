# New Tenant Onboarding: [BUSINESS NAME]

## Tenant Details
- **Tenant ID**: `[lowercase_no_spaces]`
- **Business Name**: [Full Business Name]
- **Domain(s)**: 
  - [ ] `example.com`
  - [ ] `www.example.com`
- **Primary Contact**: [Name, Email]
- **Go-Live Date**: [Target Date]

## Brand Customization
- **Primary Color**: `#2563eb` (or custom hex)
- **Chat Header**: "Chat with us" (or custom)
- **Greeting**: "Hi! How can I help you today?" (or custom)

## FAQs to Create

### Pricing
| Question | Answer | Variants |
|----------|--------|----------|
| Pricing and quotes | [Their pricing info or clarify response] | prices, how much, cost, quote, rates |

### Services
| Question | Answer | Variants |
|----------|--------|----------|
| [Service 1] | [Answer] | [variants] |
| [Service 2] | [Answer] | [variants] |

### Policies
| Question | Answer | Variants |
|----------|--------|----------|
| Cancellation policy | [Their policy] | cancel, cancellation, reschedule |
| Payment methods | [Their methods] | pay, payment, card, invoice |

### Logistics
| Question | Answer | Variants |
|----------|--------|----------|
| Service area | [Their area] | suburbs, areas, do you come to |
| Booking lead time | [Their timing] | how soon, availability, next available |

## Onboarding Steps

### 1. Create Tenant
```powershell
# Via Admin UI or API
$token = "YOUR_ADMIN_TOKEN"
curl.exe -X POST "https://motionmade-fastapi.onrender.com/admin/api/tenants" `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{\"id\":\"[TENANT_ID]\",\"name\":\"[BUSINESS NAME]\"}'
```

Or use Admin UI: https://motionmade-fastapi.onrender.com/admin

### 2. Add Domains
```powershell
# Add each domain
curl.exe -X POST "https://motionmade-fastapi.onrender.com/admin/api/tenant/[TENANT_ID]/domains" `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -d '{\"domain\":\"example.com\"}'
```

Or use Admin UI: Navigate to tenant detail page → Add Domain

### 3. Prepare FAQs JSON
Create file: `tenants/[TENANT_ID]/faqs.json`
```json
[
  {
    "question": "Pricing and quotes",
    "answer": "Our pricing depends on...",
    "variants": ["prices", "how much", "cost", "quote"]
  }
]
```

### 4. Create Test Suite
Create file: `tests/[TENANT_ID].json`
```json
{
  "tests": [
    {
      "name": "Pricing hit",
      "question": "how much do you charge",
      "expect_debug_branch_any": ["fact_hit", "fact_rewrite_hit"],
      "must_contain": ["pricing", "cost"]
    },
    {
      "name": "Unknown capability",
      "question": "do you do brain surgery",
      "expect_debug_branch_any": ["fact_miss", "general_fallback"]
    }
  ]
}
```

### 5. Upload and Promote
```powershell
cd C:\MM\motionmade-fastapi
.\run_faq_pipeline.ps1 -TenantId [TENANT_ID]
```

This will:
- Upload FAQs to staging
- Run test suite
- Promote to live if tests pass
- Create last_good backup

### 6. Verify Readiness
```powershell
curl.exe -s "https://motionmade-fastapi.onrender.com/admin/api/tenant/[TENANT_ID]/readiness" `
  -H "Authorization: Bearer $token" | ConvertFrom-Json
```

Check that all checks pass:
- ✅ Tenant exists
- ✅ Has enabled domains
- ✅ Has live FAQs
- ✅ Has last_good backup
- ✅ Has test suite file

### 7. Generate Install Snippet
Use Admin UI: Navigate to tenant detail page → "Install Snippet" section

Or manually:
```html
<script 
  src="https://mm-client1-creator-ui.pages.dev/widget.js"
  data-api="https://api.motionmadebne.com.au"
  data-greeting="Hi! How can I help you today?"
  data-header="[BUSINESS NAME] Support"
  data-color="#[THEIR_COLOR]"
  data-position="bottom-right">
</script>
```

### 8. Send to Customer
Email template:

---

**Subject:** Your AI Chat Widget is Ready!

Hi [Customer Name],

Your AI-powered chat widget is ready to go live! Here's what you need to do:

**Installation:**
1. Copy the code snippet below
2. Paste it just before the closing `</body>` tag on your website
3. That's it! The widget will appear automatically.

```html
<script 
  src="https://mm-client1-creator-ui.pages.dev/widget.js"
  data-api="https://api.motionmadebne.com.au"
  data-greeting="Hi! How can I help you today?"
  data-header="[BUSINESS NAME] Support"
  data-color="#[THEIR_COLOR]"
></script>
```

**Customization:**
- `data-greeting`: Change the initial message
- `data-header`: Change the chat window title
- `data-color`: Use your brand color (hex format, e.g., #2563eb)
- `data-position`: `bottom-right`, `bottom-left`, `top-right`, or `top-left`

**Content Security Policy (CSP):**
If you use CSP, add these to your allowlist:
- `https://mm-client1-creator-ui.pages.dev` (for widget.js)
- `https://api.motionmadebne.com.au` (for API calls)

**Testing:**
After installation, test by:
1. Opening your website
2. Clicking the chat widget (bottom-right corner)
3. Asking a question from your FAQs
4. Verifying you get the correct answer

**Support:**
If you need any changes to the FAQs or widget settings, just let me know!

Best regards,
[Your Name]

---

### 9. Post-Launch Monitoring

After go-live, monitor:
- **Stats**: Check `/admin/api/tenant/[TENANT_ID]/stats` for hit rates
- **Alerts**: Check `/admin/api/tenant/[TENANT_ID]/alerts` for warnings
- **Telemetry**: Review fallback rate - if >40%, add more FAQ variants

### 10. Ongoing Maintenance

**Update FAQs:**
1. Edit `tenants/[TENANT_ID]/faqs.json`
2. Run `.\run_faq_pipeline.ps1 -TenantId [TENANT_ID]`
3. Verify tests pass

**Rollback if needed:**
```powershell
curl.exe -X POST "https://motionmade-fastapi.onrender.com/admin/api/tenant/[TENANT_ID]/rollback" `
  -H "Authorization: Bearer $token"
```

## Checklist

- [ ] Tenant created
- [ ] Domains added and enabled
- [ ] FAQs prepared and uploaded
- [ ] Test suite created and passing
- [ ] FAQs promoted to live
- [ ] Readiness check passed
- [ ] Install snippet generated
- [ ] Customer notified with instructions
- [ ] Post-launch monitoring set up


