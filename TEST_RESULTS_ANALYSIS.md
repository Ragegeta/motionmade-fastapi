# Sparky's Electrical - Realistic Customer Question Test Results

## Test Overview

**Total Questions:** 20
**Expected Hits:** 16
**Actual Hits:** 3
**Hit Rate:** 18.8%

## Results Breakdown

### ✅ Correct Hits (3/16)
1. **T08** - "how do i book" (0.802) - Booking FAQ ✅
2. **T11** - "are you licensed" (0.827) - Licensing FAQ ✅
3. **T12** - "r u insured" (0.762) - Licensing FAQ ✅ [DISAMBIGUATED]

### ❌ Wrong Misses (13/16)
These should have hit but didn't:

| ID | Question | Score | Expected Topic | Issue |
|----|----------|-------|----------------|-------|
| T01 | "how much do you charge" | 0.453 | Pricing | Score too low |
| T02 | "ur prices pls" | 0.601 | Pricing | **In disambiguation band but below 0.65** |
| T03 | "what's your call out fee" | 0.386 | Pricing | Score too low |
| T04 | "do you do powerpoints" | 0.217 | Services | Score too low |
| T05 | "can u install ceiling fans" | 0.342 | Services | Score too low |
| T06 | "what areas do you service" | 0.585 | Area | **Close to disambiguation band** |
| T07 | "do u come to brisbane" | 0.442 | Area | Score too low |
| T09 | "can u come 2day" | 0.375 | Booking | Score too low |
| T10 | "i have no power" | 0.400 | Emergency | Score too low |
| T13 | "g'day mate, wat do u charge..." | 0.427 | Pricing | Score too low |
| T14 | "hey quick one - how much is your hourly rate" | 0.400 | Pricing | Score too low |
| T15 | "do you service logan" | 0.431 | Area | Score too low |
| T16 | "can you come this arvo" | 0.301 | Booking | Score too low |

### ✅ Correct Misses (4/4)
1. **T17** - "do you do plumbing" (0.428) - Unknown service ✅
2. **T18** - "can you fix my car" (0.290) - Unknown service ✅
3. **T19** - "???" - Junk ✅
4. **T20** - "hi" - Too vague ✅

## Disambiguation Analysis

**Disambiguation Triggered:** 1 query (T12 - "r u insured")
- Score: 0.762 (in 0.65-0.82 band)
- Result: Successfully matched licensing FAQ

**Queries That Should Have Disambiguated:**
- **T02** - "ur prices pls" (0.601) - **Below 0.65 threshold, won't trigger**
- **T06** - "what areas do you service" (0.585) - **Below 0.65 threshold, won't trigger**

## Key Findings

### 1. Hit Rate Too Low
- Only 18.8% hit rate (target: 75%+)
- Most queries scoring below 0.65
- Need better FAQ variants or embedding tuning

### 2. Disambiguation Band Too Narrow
- Current: 0.65-0.82
- T02 (0.601) and T06 (0.585) are close but below threshold
- Consider lowering to 0.60-0.82 to catch more borderline cases

### 3. No Wrong Hits
- ✅ System correctly rejects unknown services (plumbing, car repair)
- ✅ System correctly rejects junk/vague queries

### 4. Disambiguation Working
- T12 successfully used disambiguation (0.762 score)
- LLM correctly matched "r u insured" to licensing FAQ

## Recommendations

1. **Add More Variants**
   - Many normalized forms missing (e.g., "how much do you charge", "your prices please")
   - Use auto-patch script to add missing variants

2. **Consider Lowering Disambiguation Threshold**
   - Current: 0.65-0.82
   - Suggested: 0.60-0.82 (would catch T02 and T06)

3. **Improve Embedding Quality**
   - Some queries scoring very low (0.2-0.3)
   - May need better FAQ phrasing or more training data

4. **Monitor Disambiguation Usage**
   - Only 1 query triggered disambiguation
   - Most queries too low to benefit from it

## Score Distribution

- **Above 0.82 (high confidence):** 2 queries (T08, T11)
- **0.65-0.82 (disambiguation band):** 1 query (T12) ✅
- **0.50-0.65 (below disambiguation):** 2 queries (T02, T06)
- **Below 0.50 (low confidence):** 15 queries

Most queries need better variants or embedding improvements.

