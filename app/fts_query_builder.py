"""
FTS query builder module with no database dependencies.
Can be tested independently without requiring database setup.
"""


def build_fts_tsquery(query: str) -> str:
    """
    Build a loose tsquery string that improves recall for small FAQ sets.
    
    Logic:
    - Lowercase, tokenize, drop stopwords (including "out")
    - Build concept groups in order: 3-word phrases, 2-word phrases, then single tokens
    - For each concept, build (term | syn1 | syn2 ...) using only single-word synonyms
    - Dedupe and cap to max 6 terms per group
    - Combine groups:
      - 0 groups: return ""
      - 1 group: return group1
      - 2 groups: return "(g1 & g2)"
      - 3+ groups: OR of pairwise ANDs: "(g1 & g2) | (g1 & g3) | (g2 & g3) | ..."
        (matches if any 2 concepts appear, instead of requiring all)
    
    Examples:
    - "smoke alarm beeping" → OR-of-pairs structure
    - "powerpoint broken" → "(powerpoint | outlet | ...) & broken"
    - "how much" → "(price | pricing | cost | quote | callout | fee | ...)"
    - "call out fee" → "(callout | fee)" (no "out" stopword)
    """
    # Stop words to filter out (including "out" which is a PostgreSQL english stopword)
    STOP_WORDS = {"how", "much", "can", "you", "my", "the", "a", "an", "to", "for", "please", "do", "does", "what", "where", "when", "why", "is", "are", "will", "would", "could", "should", "out"}
    
    MAX_TERMS_PER_GROUP = 6  # Cap synonyms to max 6 terms per group
    
    query_lower = query.lower().strip()
    words = query_lower.split()
    
    # Synonym mappings - single-word tokens only (avoid "out" which is a stopword)
    SYNONYMS = {
        "wall plug": ["powerpoint", "outlet", "socket", "gpo"],
        "powerpoint": ["outlet", "socket", "wall", "plug", "gpo"],
        "outlet": ["powerpoint", "socket", "wall", "plug", "gpo"],
        "socket": ["powerpoint", "outlet", "wall", "plug", "gpo"],
        "power point": ["powerpoint", "outlet", "socket", "gpo"],
        "power": ["powerpoint"],
        "point": ["powerpoint"],
        "beep": ["beeping", "chirp", "chirping"],
        "beeping": ["beep", "chirp", "chirping"],
        "chirp": ["beep", "beeping", "chirping"],
        "chirping": ["beep", "beeping", "chirp"],
        "plug": ["powerpoint", "outlet", "socket"],
        "wall socket": ["powerpoint", "outlet", "socket", "wall", "plug"],
        # Pricing intent synonyms - all single tokens
        "how much": ["price", "pricing", "cost", "quote", "callout", "fee", "fees", "charge", "charges", "rates", "rate"],
        "call out": ["callout"],  # Map to single token (avoid "out")
        "call out fee": ["callout", "fee"],  # Handle as phrase, map to single tokens
        "callout": [],  # Single token, no synonyms needed
        "fee": ["callout", "price", "pricing", "cost", "charge", "charges"],
    }
    
    # Pricing intent patterns - if query matches pricing intent, return ONLY pricing synonyms
    pricing_patterns = ["how much", "how much do you charge", "how much do you", "how much does", "what do you charge"]
    has_pricing_intent = any(pattern in query_lower for pattern in pricing_patterns)
    
    # Special handling for pricing-only queries: return ONLY pricing synonym OR-group
    if has_pricing_intent:
        meaningful_words_count = len([w for w in words if w not in STOP_WORDS])
        if meaningful_words_count <= 1:
            # Replace entirely with pricing synonyms as single OR group
            synonyms = SYNONYMS.get("how much", ["price", "pricing", "cost", "quote", "callout", "fee"])
            # Filter to single-word tokens only, no stopwords
            single_tokens = [s for s in synonyms if " " not in s and "-" not in s and s not in STOP_WORDS]
            if single_tokens:
                # Cap to max 6 terms
                capped_tokens = single_tokens[:MAX_TERMS_PER_GROUP]
                return f"({' | '.join(capped_tokens)})"
            return ""
    
    # Build concept groups: 3-word phrases, then 2-word phrases, then single tokens
    concept_groups = []
    processed_indices = set()  # Track which word indices were used in phrases
    
    # First pass: check for 3-word phrases in original query
    i = 0
    while i < len(words):
        if i in processed_indices:
            i += 1
            continue
        
        # Check 3-word phrase first (like "call out fee")
        if i < len(words) - 2:
            phrase3 = f"{words[i]} {words[i+1]} {words[i+2]}"
            if phrase3 in SYNONYMS:
                # Build OR group for this phrase
                or_parts = []
                # Add original words (only meaningful, non-stopword tokens)
                for w in words[i:i+3]:
                    if w not in STOP_WORDS and len(w) > 1:
                        or_parts.append(w)
                # Add synonyms (single-word tokens only, no stopwords)
                for syn in SYNONYMS[phrase3]:
                    if " " not in syn and "-" not in syn and syn not in STOP_WORDS:
                        or_parts.append(syn)
                if or_parts:
                    # Dedupe, sort, and cap to max 6 terms
                    unique_parts = sorted(set(or_parts))[:MAX_TERMS_PER_GROUP]
                    concept_groups.append(f"({' | '.join(unique_parts)})")
                    processed_indices.update([i, i+1, i+2])
                    i += 3
                    continue
        
        i += 1
    
    # Second pass: check for 2-word phrases (only unprocessed words)
    i = 0
    while i < len(words):
        # Skip if current word is already processed
        if i in processed_indices:
            i += 1
            continue
        
        # Check 2-word phrase (like "wall plug", "power point")
        # Only if next word is also not processed
        if i < len(words) - 1 and (i+1) not in processed_indices:
            phrase2 = f"{words[i]} {words[i+1]}"
            if phrase2 in SYNONYMS:
                # Build OR group for this phrase
                or_parts = []
                # Add original words (only meaningful, non-stopword tokens)
                for w in words[i:i+2]:
                    if w not in STOP_WORDS and len(w) > 1:
                        or_parts.append(w)
                # Add synonyms (single-word tokens only, no stopwords)
                for syn in SYNONYMS[phrase2]:
                    if " " not in syn and "-" not in syn and syn not in STOP_WORDS:
                        or_parts.append(syn)
                if or_parts:
                    # Dedupe, sort, and cap to max 6 terms
                    unique_parts = sorted(set(or_parts))[:MAX_TERMS_PER_GROUP]
                    concept_groups.append(f"({' | '.join(unique_parts)})")
                    processed_indices.update([i, i+1])
                    i += 2
                    continue
        
        i += 1
    
    # Third pass: process remaining single tokens (not already in phrases)
    meaningful_words = []
    for i, w in enumerate(words):
        if i not in processed_indices and w not in STOP_WORDS and len(w) > 1:
            meaningful_words.append(w)
    
    if not meaningful_words and not concept_groups:
        return ""
    
    # Process remaining single words
    for word in meaningful_words:
        if word in SYNONYMS:
            # Build OR group: (word | syn1 | syn2 | ...)
            or_parts = [word]  # Include original word
            # Add synonyms (single-word tokens only)
            for syn in SYNONYMS[word]:
                if " " not in syn and "-" not in syn and syn not in STOP_WORDS:
                    or_parts.append(syn)
            if or_parts:
                # Dedupe, sort, and cap to max 6 terms
                unique_parts = sorted(set(or_parts))[:MAX_TERMS_PER_GROUP]
                if len(unique_parts) > 1:
                    concept_groups.append(f"({' | '.join(unique_parts)})")
                else:
                    concept_groups.append(unique_parts[0])
        else:
            # Word has no synonyms, use as-is
            concept_groups.append(word)
    
    # Combine groups according to logic:
    # 0 groups: return ""
    # 1 group: return group1
    # 2 groups: return "(g1 & g2)"
    # 3+ groups: OR of pairwise ANDs
    if not concept_groups:
        return ""
    elif len(concept_groups) == 1:
        return concept_groups[0]
    elif len(concept_groups) == 2:
        return f"({concept_groups[0]} & {concept_groups[1]})"
    else:
        # 3+ groups: build OR of all pairwise ANDs
        # (g1 & g2) | (g1 & g3) | (g2 & g3) | ...
        pairs = []
        for i in range(len(concept_groups)):
            for j in range(i + 1, len(concept_groups)):
                pairs.append(f"({concept_groups[i]} & {concept_groups[j]})")
        return " | ".join(pairs)

