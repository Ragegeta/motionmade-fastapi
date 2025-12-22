# MotionMade API — Rulebook (v1)

## What this system must do (non-negotiable)
- Business questions (pricing, inclusions, service area, capability/services) MUST NOT be answered by general AI.
- If business question hits an FAQ: return that FAQ answer (fact_hit).
- If business question does NOT hit an FAQ: return the exact fallback sentence (fact_miss).
- General questions (science, casual chat) can be general_ok.
- Public API contract is frozen (routes + JSON response keys + fallback sentence).
- No 500s. On any exception: return fallback + debug headers.

## Frozen fallback sentence
For accurate details, please contact us directly and we'll be happy to help.

## Debug headers we rely on
- x-build, x-debug-branch, x-fact-gate-hit, x-fact-domain, x-faq-hit
- x-retrieval-score, x-retrieval-delta, x-top-faq-id (when retrieval runs)
- x-proxy-upstream, x-proxy-status, x-proxy-path (proxy)

## Release branch rule
- Production deploys from: release/v1
- main is for experiments only
- Do not merge to release/v1 unless the test suite passes

## How to verify before any deploy
Run:
powershell -ExecutionPolicy Bypass -NoProfile -File C:\MM\motionmade-fastapi\test-suite.ps1

All tests must PASS.
