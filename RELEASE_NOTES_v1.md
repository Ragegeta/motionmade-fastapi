# MotionMade API — v1 (Known-good baseline)

## URLs
- Render (direct): https://motionmade-fastapi.onrender.com
- Proxy (Cloudflare): https://api.motionmadebne.com.au

## Public API (frozen)
- GET /api/health -> "ok"
- POST /api/v2/generate-quote-reply -> JSON:
  replyText, lowEstimate, highEstimate, includedServices, suggestedTimes, estimateText, jobSummaryShort, disclaimer

## Fallback sentence (frozen)
For accurate details, please contact us directly and we'll be happy to help.

## Debug headers relied on by tests
- x-build
- x-debug-branch
- x-fact-gate-hit
- x-fact-domain
- x-faq-hit
- x-retrieval-score (when retrieval runs)
- x-retrieval-delta (when retrieval runs)
- x-top-faq-id (when retrieval runs)
- x-proxy-upstream (proxy)
- x-proxy-status (proxy)
- x-proxy-path (proxy)

## Acceptance test suite
Run:
powershell -ExecutionPolicy Bypass -NoProfile -File C:\MM\motionmade-fastapi\test-suite.ps1

All tests must PASS.
