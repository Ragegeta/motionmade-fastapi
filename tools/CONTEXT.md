# Repository Context

## Product Flow
- **widget.js** → **Cloudflare Worker** (`/api/v2/widget/chat`) → Tenant routing by Origin via D1 `tenant_domains` → **FastAPI** (`/api/v2/generate-quote-reply`)

## Current Retrieval Architecture
- **Primary:** Postgres FTS/keyword-first
- **Secondary:** Embeddings
- **LLM Selector/Rerank:** Active only in "uncertain band" (0.40-0.82)
- **Cross-Encoder:** Optional; disabled by default

## Current Hard Gates (Confidence Pack Targets)
- **should-hit:** ≥85%
- **wrong-hit:** 0%
- **edge clarify:** ≥70%
- **variance:** ≤5pp
- **latency:** p50 ≤2.5s, p95 ≤6s (HTTP-only)

## Critical Ordering
- **Wrong-Service Guardrail:** Executes BEFORE cache/retrieval/fast-path (Stage 0.2 in retriever)
- **Cache Validation:** Prevents cached wrong hits (defensive check after wrong-service gate)

## Current Deployed Render SHA
- **SHA:** `fc54c00ce35c8eaf7cc795de0cb0a1ea9dc8f9b6`
- **Source:** https://motionmade-fastapi.onrender.com/api/health

## Current Known Blockers
- **Hit rate:** 80% (target ≥85%) - 5pp short
- **Edge clarify:** 28.9% (target ≥70%) - 41.1pp short
- **Latency p50:** 11.836s (target ≤2.5s) - 9.3s over
- **Latency p95:** 14.992s (target ≤6s) - 8.992s over
- **Wrong-hit:** 0% ✅ (passing)
- **Variance:** 0pp ✅ (passing)

## Next Tasks
1. **Latency Analysis:** Separate HTTP-only latency from sleeps/overhead; track `selector_called` rate
2. **Wrong-Service Intent:** Make intent-based with context allowlist for electrical symptoms
3. **Candidate Reduction:** Reduce `no_candidates` via synonym/normalization and `search_vector` rebuild

