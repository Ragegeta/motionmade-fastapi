# Customer Onboarding Checklist (8 minutes)

## Prerequisites
- Admin UI access: https://[your-admin-ui-url]
- Terminal with wrangler installed
- Customer's website domain

---

## Step 1: Create Tenant (Admin UI)
1. Go to Admin UI â†’ Tenants
2. Click "+ New Tenant"
3. Enter tenant ID (e.g., joes_plumbing)
4. Click Create

## Step 2: Add Domain (Admin UI)
1. Click on the tenant
2. In "Domains" section, click "Add Domain"
3. Enter customer's domain (e.g., joesplumbing.com.au)
4. Click Add

## Step 3: Sync Domain to Worker D1 (Terminal)
Run this command (replace DOMAIN and TENANT_ID):
```powershell
cd C:\MM\10__CLIENTS\client1\backend
wrangler d1 execute motionmade_creator_enquiries --remote --command "INSERT INTO tenant_domains (domain, tenant_id, enabled) VALUES ('CUSTOMER_DOMAIN', 'TENANT_ID', 1) ON CONFLICT(domain) DO UPDATE SET tenant_id='TENANT_ID', enabled=1;"
```

Example:
```powershell
wrangler d1 execute motionmade_creator_enquiries --remote --command "INSERT INTO tenant_domains (domain, tenant_id, enabled) VALUES ('joesplumbing.com.au', 'joes_plumbing', 1) ON CONFLICT(domain) DO UPDATE SET tenant_id='joes_plumbing', enabled=1;"
```

## Step 4: Upload FAQs (Admin UI)
1. In tenant page, find "Upload Staged FAQs (JSON)"
2. Paste the FAQ JSON (see FAQ_TEMPLATE.md)
3. Click "Upload Staged"
4. Verify "Staged: X" shows correct count

## Step 5: Promote (Admin UI)
1. Click "Promote"
2. Wait 20-30 seconds for embeddings
3. Verify "Live: X" shows correct count

## Step 6: Copy Widget Snippet (Admin UI)
1. Scroll to "Install Snippet" section
2. Customize greeting, header, color if needed
3. Click "Copy"

## Step 7: Install on Customer Site
1. Send snippet to customer (or install yourself)
2. Paste before closing </body> tag
3. Test the widget

---

## Quick Test Queries
After installation, test these in the widget:
- "pricing" or "how much"
- "what areas do you service"
- "are you available tomorrow"
- A wrong-service query (should politely decline)

---

## Troubleshooting
- **Widget doesn't appear:** Check browser console for errors
- **"Couldn't connect" error:** Domain not in D1, run Step 3 again
- **Wrong answers:** Check FAQs, may need more variants
- **Slow responses:** Normal for first query (~4s), cached queries faster

