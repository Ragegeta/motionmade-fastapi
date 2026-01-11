# FTS Analysis Summary - sparkys_electrical Confidence Pack

## Key Findings

### 1. Distribution Statistics

**Total cases: 130**

- **FTS-only usage**: 10 cases (7.7%) - TARGET: 30-60%
- **Vector ran**: 90 cases (69.2%) - TARGET: <30%
- **Neither**: 30 cases (23.1%) - wrong_service_rejected

**FTS Candidate Count Distribution:**
- 0 candidates: 120 cases (92.3%) ⚠️ **CRITICAL PROBLEM**
- 1 candidate: 10 cases (7.7%)

**All vector cases (90) had 0 FTS candidates** - This means FTS is completely failing to match, forcing everything to vector search.

### 2. Vector Cases - FTS Stats

**All 90 vector cases had 0 FTS candidates.**

Sample queries that got 0 FTS matches but should have matched:
1. "my powerpoint stopped working can you fix it"
2. "sparks coming from wall socket"
3. "lights dimming when ac turns on"
4. "circuit breaker keeps flipping"
5. "smoke alarm beeping every few minutes"
6. "safety switch tripping constantly"
7. "power went out in half the house"
8. "outlet feels hot to touch"

**These queries clearly should match FAQs, but FTS returns 0 candidates.**

### 3. Root Cause: Overly Strict tsquery Generation

**Location**: `app/retriever.py`, line 319:
```python
result = " & ".join(query_groups)  # ❌ All groups AND'd together
```

**Problem**: When `expand_query_synonyms()` finds ANY synonyms, it builds a tsquery where ALL meaningful words are AND'd together.

**Example**: Query "smoke alarm beeping"
- Stopwords filtered: ["smoke", "alarm", "beeping"]
- Synonym expansion finds "beeping" → `(beep | beeping | chirp | chirping)`
- Final tsquery: `smoke & alarm & (beep | beeping | chirp | chirping)`
- This requires ALL THREE terms to match!

**Why this fails:**
- FAQs might say "smoke detector beeping" (not "smoke alarm")
- FAQs might say "fire alarm chirping" (not "beeping")
- FAQs might say "smoke alarm battery" without the action word
- Single-word variations break the strict AND requirement

### 4. Additional Issues in tsquery Generation

**Issue 1: Multi-word synonyms become AND groups**
- Line 277, 303: `or_parts.append(f"({' & '.join(term_words)})")`
- "wall plug" → `(wall & plug)` requires both words
- Should use phrase search or OR logic

**Issue 2: No fallback to natural language**
- When synonyms are found, we ALWAYS build strict tsquery
- No hybrid approach: use synonyms but still allow flexibility

**Issue 3: All meaningful words required**
- Line 318: All query groups joined with AND
- Even if one word has synonyms, ALL words must match

### 5. Recommended Fixes

#### Fix 1: Use OR logic for major terms (high priority)

Change line 319 to use OR between major concepts, OR use websearch_to_tsquery for natural language queries:

**Option A**: Only build tsquery if we have strong synonym matches for most/all terms. Otherwise, use websearch_to_tsquery:

```python
# If less than 50% of words have synonyms, use natural language
synonym_coverage = len([w for w in meaningful_words if w in SYNONYMS]) / len(meaningful_words)
if synonym_coverage < 0.5:
    # Use websearch_to_tsquery for natural language
    return query  # Let search_fts() use websearch_to_tsquery
else:
    # Build tsquery only if most terms have synonyms
    result = " & ".join(query_groups)
    return result
```

**Option B**: Use OR logic between major terms (at least 2+ words):

```python
# If we have 3+ words, use OR between them for flexibility
if len(query_groups) >= 3:
    # Group first 2 terms with AND, rest with OR
    result = f"({' & '.join(query_groups[:2])}) | ({' | '.join(query_groups[2:])})"
else:
    result = " & ".join(query_groups)
```

**Option C**: Always use websearch_to_tsquery (simplest, recommended):

```python
# Don't build tsquery manually - let PostgreSQL handle it
# expand_query_synonyms should only add synonym words to the query
# Then use websearch_to_tsquery which handles AND/OR more intelligently
```

#### Fix 2: Make multi-word synonyms use phrase search

Instead of `(wall & plug)`, use phrase search `"wall plug":*` or OR logic.

#### Fix 3: Lower FTS-only fast path thresholds (temporary workaround)

Since FTS is currently broken (0 candidates), lowering thresholds won't help. **Fix the tsquery generation first.**

Once fixed, recommended threshold:
```python
# If FTS returns ANY candidates, trust it (very permissive)
if fts_candidate_count >= 1:
    use_fts_only_fast_path = True
```

**Expected result**: With fixed tsquery, we should see 50-80% of queries getting 1+ FTS candidates. Then we can use:
```python
fts_candidate_count >= 1 AND fts_top_score >= 0.05  # Lower score threshold
```

### 6. Concrete Recommendations

**Priority 1: Fix tsquery generation (CRITICAL)**
1. Change `expand_query_synonyms()` to return natural language more often
2. Only build strict tsquery when we have comprehensive synonym coverage
3. Use `websearch_to_tsquery()` for most queries (it's smarter about AND/OR)

**Priority 2: Test with real queries**
- After fix, test the fts-diagnostics endpoint with:
  - "smoke alarm beeping"
  - "powerpoint stopped working"
  - "circuit breaker flipping"
  - "outlet hot to touch"
- Verify `fts_matches_count > 0` for these

**Priority 3: Adjust fast path thresholds**
- After FTS recall is fixed, measure actual score distribution
- Set thresholds based on observed scores (likely 0.05-0.15 range)
- Aim for 30-60% FTS-only usage

### 7. Expected Impact

**Before fix:**
- FTS candidates: 92.3% get 0 candidates
- FTS-only usage: 7.7%
- Vector usage: 69.2%

**After fix (estimated):**
- FTS candidates: 60-80% get 1+ candidates (expected)
- FTS-only usage: 30-50% (expected)
- Vector usage: 20-40% (expected)

**Performance improvement:**
- Current: ~90% of queries go through expensive vector search
- After: ~40-60% use fast FTS-only path
- Estimated latency reduction: 30-50% for affected queries

