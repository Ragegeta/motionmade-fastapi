# Hybrid Retrieval Strategy

## Overview

Hybrid retrieval combines embedding search with LLM disambiguation for uncertain matches. This gives us the robustness of LLM understanding without generating hundreds of variants.

## Flow

1. **User asks**: "r u licensed"
2. **Normalize**: "are you licensed"
3. **Embedding search**: Find top 5 FAQ candidates
4. **If top score >= 0.82**: Return answer (high confidence)
5. **If top score 0.50-0.82**: Ask LLM to pick best match
6. **LLM returns**: Best FAQ index or "none"
7. **If LLM picks**: Return that answer (disambiguate_hit)
8. **If LLM says none**: Fallback/clarify

## Benefits

- **No need to generate 50+ variants per FAQ**
- **LLM understands semantic similarity**
- **Only called for uncertain cases (~20% of queries)**
- **Doesn't learn from production - deterministic per query**
- **Can handle questions that don't match any variant exactly**

## Cost

- Only called for 0.65-0.82 band (~15-20% of queries)
- Model: gpt-4o-mini (fast, cheap)
- Tokens: ~100 in, 1 out
- Cost: ~$0.0001 per disambiguation
- Latency: ~200-500ms added

## Failure Modes

| Failure | Behavior |
|---------|----------|
| LLM timeout (>3s) | Fall through to clarify/fallback |
| LLM error | Fall through to clarify/fallback |
| Invalid response | Fall through to clarify/fallback |
| Tenant mismatch | Log security warning, fall through |
| Score < 0.65 | Skip disambiguation, normal flow |

## What You Need To Do

1. Write clean FAQs (5-10 questions per business)
2. Add 5-10 obvious variants each
3. Upload + Promote
4. System handles uncertain matches automatically

## No More

- Generating hundreds of variants
- Auto-patching from production misses
- Worrying about edge cases

## Implementation Details

### Disambiguation Thresholds

- **THETA_HIGH = 0.82**: Above this, use embedding result directly (high confidence)
- **THETA_LOW = 0.65**: Below this, don't disambiguate (too low confidence)
- **Narrow band (0.65-0.82)**: Only ~15-20% of queries trigger disambiguation

### When Disambiguation Runs

- Top score is in uncertain zone (0.65 - 0.82)
- Narrow band minimizes LLM calls while catching uncertain matches

### LLM Prompt

The LLM sees:
- Customer's normalized question
- Top 5 FAQ candidates with:
  - FAQ question
  - Answer preview (first 150 chars)
  - Similarity score

LLM responds with:
- A number (1-5) indicating which FAQ matches
- Or "none" if no FAQ matches

## Debug Headers

- `X-Disambiguated: true` - Disambiguation was used
- `X-Debug-Branch: disambiguate_hit` - Hit via disambiguation
- `X-Retrieval-Score` - Embedding similarity score
- `X-Retrieval-Delta` - Score difference between top and runner-up

