# Launch Gates Documentation

## MANDATORY GATES (must pass before go-live)

### 1. TENANT EXISTS
- Tenant record in database
- At least 1 domain registered and enabled

### 2. FAQ MINIMUM
- At least 5 live FAQs
- Each FAQ has at least 3 variants (auto-generated is fine)

### 3. HIT RATE >= 75%
- On the standard messy benchmark (20+ test cases)
- Tests cover: pricing, services, area, booking, policies
- Includes slang/typo variants of each category

### 4. FALLBACK RATE = 0%
- Expected FAQ hits should NEVER fallback
- Clarify is allowed for junk/ambiguous

### 5. WRONG HIT RATE = 0%
- Unknown capabilities must NOT return FAQ answers
- "Do you do plumbing" for electrician must miss

### 6. JUNK HANDLING
- "???", "asdf", "hi" must return clarify response
- Not count as fallback or wrong hit

## OPTIONAL GATES (recommended but not blocking)

### 7. HIT RATE >= 85%
- Stretch goal for quality

### 8. TEST SUITE EXISTS
- Tenant-specific test file in tests/{tenant_id}.json
- At least 10 test cases

### 9. RESPONSE TIME < 2000ms
- P95 latency under 2 seconds

## GATE THRESHOLDS SUMMARY

| Metric          | Required | Ideal  |
|-----------------|----------|--------|
| Hit rate        | >= 75%   | >= 85% |
| Fallback rate   | = 0%     | = 0%   |
| Wrong hit rate  | = 0%     | = 0%   |
| Min FAQs        | 5        | 10     |
| Min variants/FAQ| 3        | 10     |

## Checking Launch Gates

Use the launch gates endpoint:

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  https://motionmade-fastapi.onrender.com/admin/api/tenant/{tenant_id}/launch-gates
```

Returns:
```json
{
  "tenant_id": "sparkys_electrical",
  "all_required_passed": true,
  "gates": [
    {
      "gate": "tenant_exists",
      "required": true,
      "passed": true,
      "message": "Tenant 'sparkys_electrical' exists"
    },
    {
      "gate": "domain_registered",
      "required": true,
      "passed": true,
      "message": "1 domain(s) registered"
    },
    ...
  ],
  "recommendation": "Ready for launch"
}
```

