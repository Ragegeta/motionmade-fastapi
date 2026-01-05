# Two-Stage Retrieval System

## Architecture

### Stage 1: Embedding Retrieval (Fast, Always Runs)
- Get top 5 candidates with similarity scores
- **Fast path**: If top score >= 0.82 → RETURN IMMEDIATELY (high confidence, no LLM needed)
- **Skip path**: If top score < 0.40 → RETURN CLARIFY (too low, don't waste LLM call)
- **Rerank path**: If 0.40-0.82 → Proceed to Stage 2

### Stage 2: LLM Rerank (Only for 0.40-0.82 Range)
- Show top 5 candidates to LLM (gpt-4o-mini)
- LLM must pick ONE FAQ and provide justification
- **Safety gates**:
  1. Must have both PICK and REASON
  2. If LLM says "none" → respect it (return None)
  3. Pick must be valid number (1-5)
  4. Reason must be non-trivial (>= 10 chars)
- If any gate fails → RETURN CLARIFY/FALLBACK

### Caching
- Cache key: `retr:{tenant_id}:{hash(normalized_query)}`
- Cache TTL: 1 hour
- Cache hit: return immediately (bypasses all retrieval)
- Cache miss: run retrieval, cache result

## Thresholds

- **THETA_HIGH = 0.82**: Above this = direct embedding hit, skip LLM
- **THETA_LOW = 0.40**: Below this = too uncertain, skip LLM (waste of money)
- **Rerank zone**: 0.40-0.82 (conditional LLM rerank)

## Response Headers

- `X-Retrieval-Stage`: `cache`, `embedding_high`, `embedding_too_low`, `rerank_hit`, `rerank_none`, `no_candidates`
- `X-Retrieval-Score`: Top embedding similarity score (0.0-1.0)
- `X-Cache-Hit`: `true`/`false`
- `X-Rerank-Triggered`: `true`/`false`
- `X-Rerank-Gate`: Safety gate result (`passed`, `llm_said_none`, `missing_pick_or_reason`, etc.)
- `X-Rerank-Ms`: LLM rerank latency in milliseconds
- `X-Retrieval-Ms`: Total retrieval latency

## Benefits

1. **Cost efficiency**: Only calls LLM for uncertain cases (0.40-0.82 band)
2. **Speed**: High-confidence hits return immediately (no LLM wait)
3. **Accuracy**: LLM rerank improves matching for messy queries
4. **Safety**: Multiple gates prevent bad matches
5. **Caching**: Reduces redundant LLM calls

## Failure Modes

| Failure | Behavior |
|---------|----------|
| LLM timeout (>3s) | Fall through to clarify/fallback |
| LLM error | Fall through to clarify/fallback |
| Invalid response | Fall through to clarify/fallback |
| Safety gate fails | Fall through to clarify/fallback |
| Score < 0.40 | Skip LLM, return None (clarify) |
| Score >= 0.82 | Direct hit, skip LLM |

## Cost Analysis

- **Embedding retrieval**: ~$0.00001 per query (OpenAI embeddings)
- **LLM rerank**: ~$0.0001 per rerank (gpt-4o-mini, ~100 tokens)
- **Expected rerank rate**: ~30-40% of queries (0.40-0.82 band)
- **Cache hit rate**: ~20-30% (reduces LLM calls)

## Implementation Files

- `app/retriever.py`: Two-stage retrieval logic
- `app/main.py`: Integration with API endpoint
- `retrieval_cache` table: Caching layer
- `faq_items.variants_json`: Stores variants for promote-time embedding

