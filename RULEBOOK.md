\# MotionMade Rulebook (Hard Rules)



\## Frozen public contract (do not change)

\- Routes stay the same:

&nbsp; - GET /api/health -> "ok"

&nbsp; - POST /api/v2/generate-quote-reply -> fixed JSON keys

\- Fallback sentence is fixed:

&nbsp; For accurate details, please contact us directly and we'll be happy to help.



\## Safety invariants (must never regress)

\- Any business / capability question must NOT return general\_ok.

\- Unknown business / capability must return the fallback sentence (HTTP 200).

\- General knowledge questions may return general\_ok.

\- Never return 500. On exception -> fallback + debug branch "error".



\## What counts as “business”

\- Pricing, inclusions, service area, booking/policy, payments/invoice

\- Capability/service questions: "do you/can you/provide/offer/service" + a service noun



\## Quality rule for FAQ variants (content-only lever)

\- Every FAQ must have at least 8–12 variants covering:

&nbsp; - formal phrasing

&nbsp; - short phrasing

&nbsp; - slang / abbreviations

&nbsp; - “do you/can you…” phrasing

\- Any time a request returns:

&nbsp; - x-fact-gate-hit=true AND x-faq-hit=false

&nbsp; -> add 2–5 targeted variants for the intended FAQ and re-upload.



\## Deployment discipline

\- Before deploying: run test-suite.ps1 and require all PASS.

\- Deploy from release/v1 branch only (once created).

\- After deploy: run test-suite.ps1 against proxy URL and require all PASS.



\## Debug headers required (do not remove)

\- x-build, x-debug-branch, x-fact-gate-hit, x-fact-domain, x-faq-hit

\- if retrieval ran: x-retrieval-score, x-retrieval-delta, x-top-faq-id

\- proxy: x-proxy-upstream, x-proxy-status, x-proxy-path



