# V1 Launch Checklist

## Pre-Launch (One-Time Setup)

- [ ] FastAPI backend deployed to Render
- [ ] Cloudflare Worker deployed
- [ ] Widget.js deployed to Cloudflare Pages
- [ ] Database schema migrated (telemetry, staging tables)
- [ ] Admin token set in environment variables

## Per-Tenant Onboarding

### 1. Create Tenant
- [ ] Add tenant record via Admin UI or API
- [ ] Note the tenant ID (e.g., `acme_cleaning`)

### 2. Register Domain(s)
- [ ] Add customer's domain(s) to `tenant_domains` table
- [ ] Include both `example.com` and `www.example.com` if needed
- [ ] Set `enabled = 1`

### 3. Upload FAQs
- [ ] Prepare FAQ JSON with questions, answers, and variants
- [ ] Upload to staging first: `PUT /admin/api/tenant/{id}/faqs/staged`
- [ ] Verify staging upload succeeded

### 4. Create Test Suite
- [ ] Create `tests/{tenant_id}.json` with test cases
- [ ] Include must-hit questions with `must_contain` assertions
- [ ] Include smoke tests (general knowledge, unknown capability)

### 5. Promote FAQs
- [ ] Run promote: `POST /admin/api/tenant/{id}/promote`
- [ ] Verify all tests pass
- [ ] Check `last_good` backup was created

### 6. Readiness Check
- [ ] Call `GET /admin/api/tenant/{id}/readiness`
- [ ] Verify all checks pass
- [ ] Address any warnings

### 7. Generate Install Snippet
- [ ] Get snippet from Admin UI "Install" section
- [ ] Customize `data-greeting`, `data-header`, `data-color` if needed
- [ ] Send to customer with installation instructions

### 8. Customer Installation
- [ ] Customer adds `<script>` to their site
- [ ] Test widget appears and responds correctly
- [ ] Verify domain routing works (no "domain not allowed" error)

### 9. Go-Live Verification
- [ ] Send test messages through live widget
- [ ] Check telemetry shows requests
- [ ] Verify hit rate is acceptable (>50%)

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

