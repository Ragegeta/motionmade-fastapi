# Tenant Onboarding Process

## Time Required: ~30 minutes

## Prerequisites
- Admin API access (ADMIN_TOKEN)
- Business details from customer

## Step 1: Gather Information (10 min)
Ask the business owner:
1. Business name
2. What services do you offer?
3. What areas do you service?
4. What's your pricing?
5. Any guarantees or trust signals? (insurance, years in business)
6. What are the 5-10 most common questions customers ask?

## Step 2: Create FAQs (10 min)
Create 5-10 FAQs covering:
- [ ] Pricing and quotes
- [ ] Services offered
- [ ] Service area
- [ ] Booking/availability
- [ ] Trust signals (insurance, guarantees)
- [ ] Industry-specific (e.g., bond back for cleaners)

Format: JSON array of `{question, answer}` objects.

## Step 3: Upload FAQs (5 min)
Tenants are created automatically when FAQs are uploaded. Use the PUT endpoint:

```bash
# Upload FAQs (creates tenant if needed)
curl -X PUT "https://api.motionmadebne.com.au/admin/tenant/{TENANT_ID}/faqs" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d @faqs.json
```

The system will:
1. Create the tenant automatically (if it doesn't exist)
2. Upload FAQs to staging
3. Generate embeddings and variants

## Step 4: Promote to Live (5 min)
Promote staged FAQs to live:

```bash
curl -X POST "https://api.motionmadebne.com.au/admin/api/tenant/{TENANT_ID}/promote" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

This will:
1. Move FAQs from staged to live
2. Create variants for better matching
3. Set up search vectors
4. Create last_good backup

## Step 5: Test (5 min)
Test with messy queries:
- "hw much do u charge"
- "wat areas u cover"
- "cn u come 2day"
- "do u do [main service]"

Verify:
- [ ] Hit rate > 85%
- [ ] Wrong-service queries rejected
- [ ] Latency < 3 seconds

## Step 6: Install Widget (optional)
Add to customer's website:
```html
<script src="https://widget.motionmade.com.au/widget.js" data-tenant="{TENANT_ID}"></script>
```

Done!

## Notes
- Tenants are created automatically when FAQs are uploaded (no separate tenant creation step needed)
- The system supports wrong-service detection (reject plumbing/electrician queries for cleaners, etc.)
- Small tenants (≤50 FAQs) use the fast path for better latency
- All queries are normalized automatically (handles messy input like "r u licenced" → "are you licensed")


