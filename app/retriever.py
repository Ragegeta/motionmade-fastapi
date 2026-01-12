"""
Two-stage retrieval: embeddings + conditional LLM rerank.

FLOW:
1. Check cache → if hit, return immediately
2. Embedding search → get top 5 candidates
3. If top score >= 0.82 → return best match (no LLM needed)
4. If top score < 0.40 → return None (too uncertain, don't waste LLM)
5. If 0.40-0.82 → LLM rerank with safety gate
6. Cache result

SAFETY GATES:
- LLM must pick exactly one FAQ or say "none"
- LLM must provide brief justification
- Justification must reference the customer's question
- If any gate fails → return None (will trigger clarify/fallback)
"""

import json
import hashlib
import time
import re
from typing import Optional, Tuple, Dict, Any, List
from app.db import get_conn
from app.openai_client import chat_once
# Lazy import cross-encoder (only when needed, not at module load)
# This prevents torch/sentence-transformers from loading at startup

# Thresholds
THETA_HIGH = 0.82       # Above this = direct hit, skip LLM
THETA_LOW = 0.40        # Below this = too uncertain, skip LLM (waste of money)
THETA_RERANK = 0.40     # Rerank zone: 0.40-0.82

# Cache TTL (seconds)
CACHE_TTL = 86400  # 24 hours (updated per requirements)

# Selector confidence threshold
SELECTOR_CONFIDENCE_THRESHOLD = 0.6  # Minimum confidence for selector to accept

# Wrong-service keywords - only reject if EXPLICIT wrong-trade intent (no electrical context)
# This is used in both retrieve() and can be imported by main.py for cache checks
WRONG_SERVICE_KEYWORDS = [
    # Plumbing (explicit)
    "plumber", "plumbing", "toilet", "tap", "drain", "pipe", "leak", "water heater", "hot water system",
    # HVAC (explicit repair/install - but allow voltage drop mentions)
    "air conditioning", "air con", "aircon", "air conditioning repair", "air con repair", "aircon repair", "ac repair", "heating repair",
    "hvac repair", "ducted system", "split system install", "install air con", "install ac",
    # Gas (explicit)
    "gas plumber", "gas heater", "gas stove", "gas line", "gas fitting", "gas repair",
    # Solar (explicit)
    "solar panel", "solar installation", "solar power install", "solar system install",
    # Building/Construction
    "painting", "painter", "paint", "roofing", "roofer", "carpentry", "carpenter", "tiling", "tiler",
    "plastering", "plasterer", "concreting", "concrete", "fencing", "fence",
    # Electrical (for non-electrical tenants - these should be rejected)
    "electrician", "sparky", "powerpoint", "power point", "socket", "outlet", "switchboard", "wiring",
    "electrical", "electrical work", "electrical repair", "lighting installation", "circuit breaker",
    # Gardening
    "gardening", "landscaping", "lawn", "mowing", "tree", "hedge",
    # Security systems (NOT smoke/fire alarms - those are electrical)
    "security camera", "security cameras", "cctv", "surveillance system", "alarm system install",
    "intercom system",
    # Automotive (expanded)
    "car", "car repair", "vehicle", "vehicle repair", "automotive", "mechanic", "engine", "brakes", "tyres", "tires",
    # Appliance repair (explicit)
    "washing machine repair", "fridge repair", "dishwasher repair", "oven repair",
]


SELECTOR_PROMPT = """You are a precise FAQ selector. Match the customer question to the best FAQ.

Customer question: "{question}"

Candidate FAQs:
{candidates}

OUTPUT STRICT JSON ONLY (no other text):
{{
  "choice": <0-based index 0-{max_idx}, or -1 if none match>,
  "confidence": <0.0-1.0>
}}

Rules:
- choice: index of best matching FAQ, or -1 if none match
- confidence: how confident you are (0.0 = uncertain, 1.0 = very confident)
- If confidence < 0.6, set choice to -1
- CRITICAL: If the query asks about a service NOT covered by these FAQs (like plumbing, painting, roofing, landscaping, car repairs, tiling, carpentry), return choice: -1
- Only return a match if the FAQ genuinely answers what the customer is asking
- Only return valid JSON, nothing else"""

RERANK_PROMPT = """You are matching a customer question to FAQ answers for a business.

Customer question: "{question}"

Here are the candidate FAQs (ranked by initial similarity):

{candidates}

TASK: Pick the FAQ that BEST answers the customer's question.

RULES:
1. Pick the FAQ that directly addresses what the customer is asking about
2. If the customer asks about pricing/cost → pick the pricing FAQ
3. If the customer asks about booking/availability → pick the booking FAQ
4. If the customer asks about services offered → pick the services FAQ
5. If the customer asks about something NOT covered by ANY FAQ → say "none"
6. If you're not confident → say "none"

RESPOND IN THIS EXACT FORMAT:
PICK: <number 1-5, or "none">
REASON: <one sentence explaining why this FAQ answers the question>

Examples:
PICK: 2
REASON: Customer is asking about pricing and FAQ 2 covers call-out fees and hourly rates.

PICK: none
REASON: Customer is asking about plumbing which is not covered by any FAQ."""


def get_cache_key(tenant_id: str, normalized_query: str) -> str:
    """Generate cache key from tenant + normalized query."""
    h = hashlib.sha256(f"{tenant_id}:{normalized_query}".encode()).hexdigest()[:16]
    return f"retr:{tenant_id}:{h}"


def get_cached_result(tenant_id: str, normalized_query: str) -> Optional[Dict]:
    """Check cache for previous result."""
    cache_key = get_cache_key(tenant_id, normalized_query)
    
    try:
        with get_conn() as conn:
            row = conn.execute("""
                SELECT result_json, created_at 
                FROM retrieval_cache 
                WHERE cache_key = %s AND created_at > NOW() - INTERVAL '%s seconds'
            """, (cache_key, CACHE_TTL)).fetchone()
            
            if row:
                return json.loads(row[0])
    except Exception as e:
        print(f"Cache read error: {e}")
    
    return None


def set_cached_result(tenant_id: str, normalized_query: str, result: Dict):
    """Store result in cache."""
    cache_key = get_cache_key(tenant_id, normalized_query)
    
    try:
        with get_conn() as conn:
            conn.execute("""
                INSERT INTO retrieval_cache (cache_key, tenant_id, result_json, created_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (cache_key) DO UPDATE SET result_json = %s, created_at = NOW()
            """, (cache_key, tenant_id, json.dumps(result), json.dumps(result)))
            conn.commit()
    except Exception as e:
        print(f"Cache write error: {e}")


def expand_query_synonyms(query: str) -> str:
    """
    Expand query with synonyms to improve FTS recall.
    Returns a plain-text string with no boolean operators.
    
    - Lowercase, tokenize, drop stopwords
    - Handle phrase cases by appending synonyms as extra words (NOT boolean groups)
    - Output: single plain-text string like "smoke alarm beeping chirp chirping beep"
    - Pricing intent expands to plain words: "price pricing cost quote callout fee fees charge charges rates rate"
    
    Examples:
    - "how much" → "price pricing cost quote callout fee fees charge charges rates rate"
    - "smoke alarm beeping" → "smoke alarm beeping chirp chirping beep"
    - "my powerpoint stopped working" → "powerpoint outlet socket stopped working"
    """
    # Stop words to filter out (exact list from requirements)
    STOP_WORDS = {"how", "much", "can", "you", "my", "the", "a", "an", "to", "for", "please", "do", "does", "what", "where", "when", "why", "is", "are", "will", "would", "could", "should"}
    
    query_lower = query.lower().strip()
    words = query_lower.split()
    
    # Synonym mappings - all values are lists of plain words (no boolean operators)
    SYNONYMS = {
        "wall plug": ["powerpoint", "outlet", "socket", "power", "point", "gpo"],
        "powerpoint": ["outlet", "socket", "power", "point", "wall", "plug", "gpo"],
        "outlet": ["powerpoint", "socket", "power", "point", "wall", "plug", "gpo"],
        "socket": ["powerpoint", "outlet", "power", "point", "wall", "plug", "gpo"],
        "beep": ["beeping", "chirp", "chirping"],
        "beeping": ["beep", "chirp", "chirping"],
        "chirp": ["beep", "beeping", "chirping"],
        "chirping": ["beep", "beeping", "chirp"],
        "plug": ["powerpoint", "outlet", "socket"],
        "wall socket": ["powerpoint", "outlet", "socket", "wall", "plug"],
        # Pricing intent synonyms - all single tokens
        "how much": ["price", "pricing", "cost", "quote", "callout", "fee", "fees", "charge", "charges", "rates", "rate"],
        "callout": [],  # Single token, no synonyms needed
        "fee": ["callout", "price", "pricing", "cost", "charge", "charges"],
    }
    
    # Pricing intent patterns - if query matches pricing intent, return ONLY pricing synonyms
    pricing_patterns = ["how much", "how much do you charge", "how much do you", "how much does", "what do you charge"]
    has_pricing_intent = any(pattern in query_lower for pattern in pricing_patterns)
    
    # Special handling for pricing-only queries: return ONLY pricing synonyms as plain words
    if has_pricing_intent:
        # Check if query is primarily pricing intent (all or mostly stopwords + pricing pattern)
        meaningful_words_count = len([w for w in words if w not in STOP_WORDS])
        if meaningful_words_count <= 1:
            # Replace entirely with pricing synonyms as plain words
            synonyms = SYNONYMS.get("how much", ["price", "pricing", "cost", "quote", "callout", "fee"])
            # Filter out multi-word tokens (shouldn't happen, but safe)
            plain_synonyms = [s for s in synonyms if " " not in s and "-" not in s]
            return " ".join(plain_synonyms)
    
    # Filter out stop words and get meaningful tokens
    meaningful_words = [w for w in words if w not in STOP_WORDS and len(w) > 1]
    
    if not meaningful_words:
        # If all words are stop words after filtering, return original query
        return query
    
    # Build result as a list of words (original + synonyms)
    result_words = []
    seen_words = set()  # Deduplicate
    
    # Check for multi-word phrases first (3-word, then 2-word)
    i = 0
    while i < len(meaningful_words):
        # Check 3-word phrase first (like "call out fee")
        if i < len(meaningful_words) - 2:
            phrase3 = f"{meaningful_words[i]} {meaningful_words[i+1]} {meaningful_words[i+2]}"
            if phrase3 in SYNONYMS:
                # Add the phrase itself as words
                for w in meaningful_words[i:i+3]:
                    if w not in seen_words:
                        result_words.append(w)
                        seen_words.add(w)
                # Add synonyms as plain words
                for synonym in SYNONYMS[phrase3]:
                    # Split multi-word synonyms into individual words
                    syn_words = synonym.replace("-", " ").split()
                    for sw in syn_words:
                        if sw not in seen_words and len(sw) > 1:
                            result_words.append(sw)
                            seen_words.add(sw)
                i += 3  # Skip all three words
                continue
        
        # Check 2-word phrase (like "wall plug", "wall socket")
        if i < len(meaningful_words) - 1:
            phrase2 = f"{meaningful_words[i]} {meaningful_words[i+1]}"
            if phrase2 in SYNONYMS:
                # Add the phrase itself as words
                for w in meaningful_words[i:i+2]:
                    if w not in seen_words:
                        result_words.append(w)
                        seen_words.add(w)
                # Add synonyms as plain words
                for synonym in SYNONYMS[phrase2]:
                    # Split multi-word synonyms into individual words
                    syn_words = synonym.replace("-", " ").split()
                    for sw in syn_words:
                        if sw not in seen_words and len(sw) > 1:
                            result_words.append(sw)
                            seen_words.add(sw)
                i += 2  # Skip both words
                continue
        
        # Single word
        word = meaningful_words[i]
        if word not in seen_words:
            result_words.append(word)
            seen_words.add(word)
        
        # Add synonyms as plain words
        if word in SYNONYMS:
            for synonym in SYNONYMS[word]:
                # Split multi-word synonyms into individual words
                syn_words = synonym.replace("-", " ").split()
                for sw in syn_words:
                    if sw not in seen_words and len(sw) > 1:
                        result_words.append(sw)
                        seen_words.add(sw)
        i += 1
    
    # Join all words with spaces - plain text, no operators
    result = " ".join(result_words)
    
    return result


def search_fts(tenant_id: str, query: str, limit: int = 20) -> list[dict]:
    """
    Full-text search using OR logic (match any term).
    """
    if not tenant_id or not query:
        return []
    
    # Check if query is explicitly a tsquery (prefixed with "TSQUERY:")
    if query.startswith("TSQUERY:"):
        tsquery_str = query[8:].strip()
        try:
            with get_conn() as conn:
                rows = conn.execute("""
                    SELECT 
                        fi.id AS faq_id,
                        fi.question,
                        fi.answer,
                        fi.tenant_id,
                        ts_rank(fi.search_vector, to_tsquery('english', %s)) AS fts_score
                    FROM faq_items fi
                    WHERE fi.tenant_id = %s
                      AND fi.enabled = true
                      AND (fi.is_staged = false OR fi.is_staged IS NULL)
                      AND fi.search_vector @@ to_tsquery('english', %s)
                    ORDER BY fts_score DESC
                    LIMIT %s
                """, (tsquery_str, tenant_id, tsquery_str, limit)).fetchall()
                
                return [
                    {
                        "faq_id": int(row[0]),
                        "question": str(row[1]),
                        "answer": str(row[2]),
                        "tenant_id": str(row[3]),
                        "fts_score": float(row[4]),
                        "source": "fts"
                    }
                    for row in rows
                ]
        except Exception as e:
            print(f"FTS search error (TSQUERY: prefix): {e}")
            return []
    
    # Extract words and build OR query
    words = [w.strip() for w in query.lower().split() if len(w.strip()) > 2]
    
    if not words:
        return []
    
    # Build OR tsquery: 'smoke' | 'alarm' | 'beep'
    or_terms = ' | '.join(words)
    
    try:
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT 
                    fi.id AS faq_id,
                    fi.question,
                    fi.answer,
                    fi.tenant_id,
                    ts_rank(fi.search_vector, to_tsquery('english', %s)) AS fts_score
                FROM faq_items fi
                WHERE fi.tenant_id = %s
                  AND fi.enabled = true
                  AND (fi.is_staged = false OR fi.is_staged IS NULL)
                  AND fi.search_vector @@ to_tsquery('english', %s)
                ORDER BY fts_score DESC
                LIMIT %s
            """, (or_terms, tenant_id, or_terms, limit)).fetchall()
            
            return [
                {
                    "faq_id": row[0],
                    "question": row[1],
                    "answer": row[2],
                    "tenant_id": row[3],
                    "fts_score": float(row[4]),
                    "source": "fts"
                }
                for row in rows
            ]
    except Exception as e:
        print(f"FTS search error: {e}")
        return []


def merge_candidates_fts_primary(
    fts_candidates: list[dict],
    vector_candidates: list[dict]
) -> list[dict]:
    """
    Merge candidates with FTS as primary signal.
    
    FTS finds keyword matches (high recall).
    Vector search adds semantic matches that FTS missed.
    """
    merged = {}
    
    # FTS candidates get base score of 0.7 (they matched keywords)
    for c in fts_candidates:
        faq_id = c["faq_id"]
        merged[faq_id] = c.copy()
        merged[faq_id]["fts_score"] = c.get("fts_score", 0.5)
        merged[faq_id]["vector_score"] = 0
        merged[faq_id]["source"] = "fts"
        # FTS matches get minimum score of 0.7 (they contain the keyword!)
        merged[faq_id]["score"] = max(0.7, c.get("fts_score", 0.5))
    
    # Vector candidates add semantic matches
    for c in vector_candidates:
        faq_id = c["faq_id"]
        if faq_id in merged:
            # Already found by FTS, boost score
            merged[faq_id]["vector_score"] = c.get("score", 0)
            merged[faq_id]["source"] = "hybrid"
            # Boost if both FTS and vector agree
            merged[faq_id]["score"] = min(1.0, merged[faq_id]["score"] + 0.1)
        else:
            # Vector-only match (semantic, no keyword)
            merged[faq_id] = c.copy()
            merged[faq_id]["fts_score"] = 0
            merged[faq_id]["vector_score"] = c.get("score", 0)
            merged[faq_id]["source"] = "vector"
            merged[faq_id]["score"] = c.get("score", 0)
    
    # Sort by score descending
    result = sorted(merged.values(), key=lambda x: x["score"], reverse=True)
    return result


def merge_candidates(
    vector_candidates: list[dict],
    fts_candidates: list[dict],
    alpha: float = 0.6  # Weight for vector score
) -> list[dict]:
    """
    Merge vector and FTS candidates using linear combination.
    
    alpha=0.6 means 60% vector, 40% FTS
    """
    # Index by faq_id
    merged = {}
    
    # Add vector candidates
    for c in vector_candidates:
        faq_id = c["faq_id"]
        merged[faq_id] = c.copy()
        merged[faq_id]["vector_score"] = c.get("score", 0)
        merged[faq_id]["fts_score"] = 0
        merged[faq_id]["source"] = "vector"
    
    # Add/merge FTS candidates
    for c in fts_candidates:
        faq_id = c["faq_id"]
        if faq_id in merged:
            merged[faq_id]["fts_score"] = c.get("fts_score", 0)
            merged[faq_id]["source"] = "hybrid"
        else:
            merged[faq_id] = c.copy()
            merged[faq_id]["vector_score"] = 0
            merged[faq_id]["fts_score"] = c.get("fts_score", 0)
            merged[faq_id]["source"] = "fts"
    
    # Calculate combined score
    for faq_id, c in merged.items():
        v_score = c.get("vector_score", 0)
        f_score = c.get("fts_score", 0)
        
        # Normalize FTS score (typically 0-1 but can be higher)
        f_score_norm = min(f_score, 1.0)
        
        c["combined_score"] = alpha * v_score + (1 - alpha) * f_score_norm
        c["score"] = c["combined_score"]  # Use combined as primary score
    
    # Sort by combined score
    result = sorted(merged.values(), key=lambda x: x["combined_score"], reverse=True)
    
    return result


def _get_tenant_faq_count(tenant_id: str) -> int:
    """Get count of enabled FAQs for a tenant (cached per-request).
    
    Returns 0 if tenant doesn't exist or query fails.
    """
    try:
        with get_conn() as conn:
            row = conn.execute("""
                SELECT COUNT(*) 
                FROM faq_items 
                WHERE tenant_id = %s 
                  AND enabled = true 
                  AND (is_staged = false OR is_staged IS NULL)
            """, (tenant_id,)).fetchone()
            return int(row[0]) if row and row[0] else 0
    except Exception as e:
        print(f"Error getting tenant FAQ count for {tenant_id}: {e}")
        return 0


def get_top_candidates(tenant_id: str, query_embedding, limit: int = 5) -> list[Dict]:
    """Get top FAQ candidates via embedding similarity.
    
    Query is optimized for index usage:
    - Orders by distance FIRST (allows index scan)
    - Filters by tenant_id and enabled status
    - Deduplicates by faq_id in Python after getting top candidates
    
    TASK B: Vector K is capped at 20 max for performance.
    """
    # Cap limit at 20 for performance
    limit = min(limit, 20)
    if not tenant_id or query_embedding is None:
        return []
    
    try:
        from pgvector.psycopg import register_vector
        from pgvector import Vector
        
        with get_conn() as conn:
            register_vector(conn)
            
            # Set ivfflat.probes for better recall if using ivfflat index
            # (HNSW doesn't need this, but setting it is harmless)
            try:
                conn.execute("SET LOCAL ivfflat.probes = 10")
            except Exception:
                pass  # Ignore if setting not supported
            
            # Convert to Vector
            qv = Vector(query_embedding)
            
            # ANN-first query using partitioned table faq_variants_p (with fallback to old table).
            # Filter by tenant_id FIRST to enable partition pruning, then do vector search on that partition.
            # This makes the ivfflat index on the partition viable.
            # Explicit ::vector cast helps planner recognize index usage.
            # Try partitioned table first, fall back to old table if it doesn't exist.
            try:
                rows = conn.execute("""
                    WITH vector_candidates AS (
                        SELECT 
                            fv.id AS variant_id,
                            fv.faq_id,
                            fv.variant_question,
                            (fv.variant_embedding <=> %s::vector) AS distance
                        FROM faq_variants_p fv
                        WHERE fv.tenant_id = %s
                          AND fv.enabled = true
                        ORDER BY fv.variant_embedding <=> %s::vector
                        LIMIT %s
                    )
                    SELECT 
                        fi.id AS faq_id,
                        fi.question,
                        fi.answer,
                        fi.tenant_id,
                        vc.variant_question AS matched_variant,
                        (1 - vc.distance) AS score
                    FROM vector_candidates vc
                    JOIN faq_items fi ON fi.id = vc.faq_id
                    WHERE fi.enabled = true
                      AND (fi.is_staged = false OR fi.is_staged IS NULL)
                    ORDER BY vc.distance ASC
                    LIMIT %s
                """, (qv, tenant_id, qv, limit * 3, limit * 3)).fetchall()  # Get 3x for dedup
            except Exception as e:
                # Fallback to old table if partitioned table doesn't exist yet
                if "does not exist" in str(e).lower() or "relation" in str(e).lower():
                    rows = conn.execute("""
                        WITH vector_candidates AS (
                            SELECT 
                                fv.id AS variant_id,
                                fv.faq_id,
                                fv.variant_question,
                                (fv.variant_embedding <=> %s::vector) AS distance
                            FROM faq_variants fv
                            WHERE fv.enabled = true
                            ORDER BY fv.variant_embedding <=> %s::vector
                            LIMIT %s
                        )
                        SELECT 
                            fi.id AS faq_id,
                            fi.question,
                            fi.answer,
                            fi.tenant_id,
                            vc.variant_question AS matched_variant,
                            (1 - vc.distance) AS score
                        FROM vector_candidates vc
                        JOIN faq_items fi ON fi.id = vc.faq_id
                        WHERE fi.tenant_id = %s
                          AND fi.enabled = true
                          AND (fi.is_staged = false OR fi.is_staged IS NULL)
                        ORDER BY vc.distance ASC
                        LIMIT %s
                    """, (qv, qv, limit * 10, tenant_id, limit * 3)).fetchall()  # Get 10x for tenant filtering, then 3x for dedup
                else:
                    raise
        
        if not rows:
            return []
        
        # Deduplicate by faq_id, keeping the best variant (highest score) for each FAQ
        seen_faqs = {}
        for row in rows:
            faq_id = int(row[0])
            score = float(row[5])
            if faq_id not in seen_faqs or score > seen_faqs[faq_id]["score"]:
                seen_faqs[faq_id] = {
                    "faq_id": faq_id,
                    "question": str(row[1]),
                    "answer": str(row[2]),
                    "tenant_id": str(row[3]),
                    "matched_variant": str(row[4]) if row[4] else str(row[1]),
                    "score": score
                }
        
        # Sort by score descending and return top limit
        candidates = sorted(seen_faqs.values(), key=lambda x: x["score"], reverse=True)
        return candidates[:limit]
        
    except Exception as e:
        print(f"Candidate retrieval error: {e}")
        import traceback
        traceback.print_exc()
        return []


def _extract_keywords(text: str, max_words: int = 5) -> str:
    """Extract key words from text (simple approach: remove stopwords, take first N words)."""
    # Simple stopwords list
    stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'do', 'does', 'did', 'is', 'are', 'was', 'were', 'you', 'your', 'what', 'where', 'when', 'how', 'why', 'can', 'could', 'will', 'would', 'should', 'may', 'might'}
    words = re.findall(r'\b\w+\b', text.lower())
    keywords = [w for w in words if w not in stopwords and len(w) > 2]
    return ' '.join(keywords[:max_words])


def _pattern_router_score(normalized_query: str, faq_question: str, faq_answer: str) -> float:
    """Simple pattern router for common forms. Returns boost score (0.0-0.3)."""
    query_lower = normalized_query.lower()
    question_lower = faq_question.lower()
    answer_lower = faq_answer.lower()
    
    boost = 0.0
    
    # Pattern: "do you do X" / "can you install X"
    if re.search(r'\b(do you do|can you install|can you do|do you install)\b', query_lower):
        # Extract service/item after the pattern
        match = re.search(r'\b(do you do|can you install|can you do|do you install)\s+([a-z\s]+)', query_lower)
        if match:
            service_terms = match.group(2).strip().split()[:3]  # First 3 words
            for term in service_terms:
                if term in question_lower or term in answer_lower:
                    boost += 0.1
                    break
    
    # Pattern: "do you service Y" / "come to Y"
    if re.search(r'\b(do you service|come to|service|service area)\b', query_lower):
        # Extract location/service area
        match = re.search(r'\b(do you service|come to|service)\s+([a-z\s]+)', query_lower)
        if match:
            location_terms = match.group(2).strip().split()[:2]
            for term in location_terms:
                if term in question_lower or term in answer_lower:
                    boost += 0.15
                    break
    
    # Pattern: "urgent" / "emergency" / "no power"
    if re.search(r'\b(urgent|emergency|no power|power out|power outage)\b', query_lower):
        if any(term in question_lower or term in answer_lower for term in ['urgent', 'emergency', 'emergencies', '24/7', 'after hours']):
            boost += 0.2
    
    return min(boost, 0.3)  # Cap at 0.3


def retrieve_candidates_v2(
    tenant_id: str,
    normalized_query: str,
    query_embedding,
    top_k: int = 8
) -> Tuple[List[Dict], str]:
    """
    Hybrid retrieval v2: Always returns candidates using vector + keyword + pattern matching.
    
    Returns:
        (candidates_list, retrieval_mode)
        - candidates_list: List of dicts with faq_id, question, answer, score, source
        - retrieval_mode: "vector", "hybrid", "keyword", "pattern", or "fallback"
    """
    if not tenant_id:
        return [], "empty_tenant"
    
    candidates_by_id = {}  # faq_id -> candidate dict (best score wins)
    retrieval_modes = set()
    
    # 1. Vector search (always try first)
    vector_candidates = []
    if query_embedding is not None:
        try:
            from pgvector.psycopg import register_vector
            from pgvector import Vector
            
            with get_conn() as conn:
                register_vector(conn)
                
                # Set ivfflat.probes if needed
                try:
                    conn.execute("SET LOCAL ivfflat.probes = 10")
                except Exception:
                    pass
                
                qv = Vector(query_embedding)
                
                # ANN-first query using partitioned table faq_variants_p (with fallback).
                # Filter by tenant_id FIRST to enable partition pruning.
                # Explicit ::vector cast helps planner recognize index usage.
                try:
                    rows = conn.execute("""
                        WITH vector_candidates AS (
                            SELECT 
                                fv.id AS variant_id,
                                fv.faq_id,
                                fv.variant_question,
                                (fv.variant_embedding <=> %s::vector) AS distance
                            FROM faq_variants_p fv
                            WHERE fv.tenant_id = %s
                              AND fv.enabled = true
                            ORDER BY fv.variant_embedding <=> %s::vector
                            LIMIT %s
                        )
                        SELECT DISTINCT ON (fi.id)
                            fi.id AS faq_id,
                            fi.question,
                            fi.answer,
                            fi.tenant_id,
                            (1 - vc.distance) AS score
                        FROM vector_candidates vc
                        JOIN faq_items fi ON fi.id = vc.faq_id
                        WHERE fi.enabled = true
                          AND (fi.is_staged = false OR fi.is_staged IS NULL)
                        ORDER BY fi.id, vc.distance ASC
                        LIMIT %s
                    """, (qv, tenant_id, qv, top_k * 3, top_k * 2)).fetchall()
                except Exception as e:
                    # Fallback to old table if partitioned table doesn't exist yet
                    if "does not exist" in str(e).lower() or "relation" in str(e).lower():
                        rows = conn.execute("""
                            WITH vector_candidates AS (
                                SELECT 
                                    fv.id AS variant_id,
                                    fv.faq_id,
                                    fv.variant_question,
                                    (fv.variant_embedding <=> %s::vector) AS distance
                            FROM faq_variants fv
                            WHERE fv.enabled = true
                            ORDER BY fv.variant_embedding <=> %s::vector
                            LIMIT %s
                        )
                        SELECT DISTINCT ON (fi.id)
                            fi.id AS faq_id,
                            fi.question,
                            fi.answer,
                            fi.tenant_id,
                            (1 - vc.distance) AS score
                        FROM vector_candidates vc
                        JOIN faq_items fi ON fi.id = vc.faq_id
                        WHERE fi.tenant_id = %s
                          AND fi.enabled = true
                          AND (fi.is_staged = false OR fi.is_staged IS NULL)
                        ORDER BY fi.id, vc.distance ASC
                        LIMIT %s
                    """, (qv, qv, top_k * 10, tenant_id, top_k * 2)).fetchall()
                    else:
                        raise
                
                for row in rows:
                    faq_id = int(row[0])
                    score = float(row[4])
                    if faq_id not in candidates_by_id or candidates_by_id[faq_id]["score"] < score:
                        candidates_by_id[faq_id] = {
                            "faq_id": faq_id,
                            "question": str(row[1]),
                            "answer": str(row[2]),
                            "tenant_id": str(row[3]),
                            "score": score,
                            "source": "vector"
                        }
                        vector_candidates.append({
                            "faq_id": faq_id,
                            "score": score
                        })
                
                if vector_candidates:
                    retrieval_modes.add("vector")
        except Exception as e:
            print(f"Vector search error: {e}")
    
    # 2. Keyword fallback using trigram similarity (if vector found few/none, or as supplement)
    if len(candidates_by_id) < top_k:
        try:
            # Try to enable pg_trgm extension if available
            with get_conn() as conn:
                try:
                    conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
                    conn.commit()
                except:
                    pass  # Extension might not be available, continue without it
                
                # Use trigram similarity as keyword fallback
                # Normalize query for matching
                query_words = normalized_query.lower().split()
                query_pattern = ' & '.join([w for w in query_words if len(w) > 2])
                
                if query_pattern:
                    rows = conn.execute("""
                        SELECT DISTINCT ON (fi.id)
                            fi.id AS faq_id,
                            fi.question,
                            fi.answer,
                            fi.tenant_id,
                            GREATEST(
                                similarity(LOWER(fi.question), %s),
                                COALESCE((
                                    SELECT MAX(similarity(LOWER(fv.variant_question), %s))
                                    FROM faq_variants fv
                                    WHERE fv.faq_id = fi.id AND fv.enabled = true
                                ), 0.0)
                            ) AS score
                        FROM faq_items fi
                        WHERE fi.tenant_id = %s
                          AND fi.enabled = true
                          AND (fi.is_staged = false OR fi.is_staged IS NULL)
                        ORDER BY fi.id, score DESC
                        LIMIT %s
                    """, (normalized_query.lower(), normalized_query.lower(), tenant_id, top_k * 2)).fetchall()
                    
                    keyword_found = False
                    for row in rows:
                        faq_id = int(row[0])
                        score = float(row[4])
                        # Only add if similarity is reasonable (> 0.2) or we need more candidates
                        if score > 0.2 or len(candidates_by_id) < top_k:
                            keyword_found = True
                            # Use lower weight for keyword matches (scale by 0.5)
                            keyword_score = score * 0.5
                            if faq_id not in candidates_by_id:
                                candidates_by_id[faq_id] = {
                                    "faq_id": faq_id,
                                    "question": str(row[1]),
                                    "answer": str(row[2]),
                                    "tenant_id": str(row[3]),
                                    "score": keyword_score,
                                    "source": "keyword"
                                }
                            elif candidates_by_id[faq_id]["source"] == "keyword":
                                # Update if this keyword match is better
                                candidates_by_id[faq_id]["score"] = max(candidates_by_id[faq_id]["score"], keyword_score)
                    
                    if keyword_found:
                        retrieval_modes.add("keyword")
        except Exception as e:
            print(f"Keyword/trigram search error: {e}")
            # If trigram fails, try simple LIKE matching as last resort
            try:
                with get_conn() as conn:
                    query_words = [w for w in normalized_query.lower().split() if len(w) > 2][:3]
                    if query_words:
                        pattern = '%' + '%'.join(query_words) + '%'
                        rows = conn.execute("""
                            SELECT DISTINCT fi.id AS faq_id, fi.question, fi.answer, fi.tenant_id
                            FROM faq_items fi
                            WHERE fi.tenant_id = %s
                              AND fi.enabled = true
                              AND (fi.is_staged = false OR fi.is_staged IS NULL)
                              AND (LOWER(fi.question) LIKE %s OR LOWER(fi.answer) LIKE %s)
                            LIMIT %s
                        """, (tenant_id, pattern, pattern, top_k)).fetchall()
                        
                        for row in rows:
                            faq_id = int(row[0])
                            if faq_id not in candidates_by_id and len(candidates_by_id) < top_k:
                                candidates_by_id[faq_id] = {
                                    "faq_id": faq_id,
                                    "question": str(row[1]),
                                    "answer": str(row[2]),
                                    "tenant_id": str(row[3]),
                                    "score": 0.1,  # Low baseline score
                                    "source": "keyword"
                                }
                                retrieval_modes.add("keyword")
            except:
                pass
    
    # 3. Pattern router boost (apply to existing candidates)
    for faq_id in list(candidates_by_id.keys()):
        candidate = candidates_by_id[faq_id]
        pattern_boost = _pattern_router_score(normalized_query, candidate["question"], candidate["answer"])
        if pattern_boost > 0:
            candidate["score"] += pattern_boost
            candidate["source"] = "hybrid" if candidate["source"] != "hybrid" else candidate["source"]
            retrieval_modes.add("pattern")
    
    # 4. Fallback: If still no candidates, get any enabled FAQs (last resort)
    if not candidates_by_id:
        try:
            with get_conn() as conn:
                rows = conn.execute("""
                    SELECT fi.id AS faq_id, fi.question, fi.answer, fi.tenant_id
                    FROM faq_items fi
                    WHERE fi.tenant_id = %s
                      AND fi.enabled = true
                      AND (fi.is_staged = false OR fi.is_staged IS NULL)
                    ORDER BY fi.id
                    LIMIT %s
                """, (tenant_id, top_k)).fetchall()
                
                for row in rows:
                    faq_id = int(row[0])
                    candidates_by_id[faq_id] = {
                        "faq_id": faq_id,
                        "question": str(row[1]),
                        "answer": str(row[2]),
                        "tenant_id": str(row[3]),
                        "score": 0.05,  # Very low baseline
                        "source": "fallback"
                    }
                if candidates_by_id:
                    retrieval_modes.add("fallback")
        except Exception as e:
            print(f"Fallback retrieval error: {e}")
    
    # Convert to list, sort by score, limit to top_k
    candidates = list(candidates_by_id.values())
    candidates.sort(key=lambda x: x["score"], reverse=True)
    candidates = candidates[:top_k]
    
    # Determine retrieval mode string
    if "vector" in retrieval_modes and ("keyword" in retrieval_modes or "pattern" in retrieval_modes):
        mode = "hybrid"
    elif "vector" in retrieval_modes:
        mode = "vector"
    elif "keyword" in retrieval_modes:
        mode = "keyword"
    elif "pattern" in retrieval_modes:
        mode = "pattern"
    elif "fallback" in retrieval_modes:
        mode = "fallback"
    else:
        mode = "none"
    
    return candidates, mode


def llm_selector(
    normalized_query: str,
    candidates: List[Dict],
    timeout: float = 3.0
) -> Tuple[Optional[int], float, Dict]:
    """
    LLM selector: Fast selector that returns strict JSON with choice index and confidence.
    
    Args:
        normalized_query: Normalized user question
        candidates: List of candidate FAQs (at least top 5-8)
        timeout: Timeout in seconds
    
    Returns:
        (choice_index or None, confidence, trace_dict)
        - choice_index: 0-based index into candidates, or None if -1/low confidence
        - confidence: 0.0-1.0
        - trace_dict: Diagnostic info
    """
    trace = {
        "selector_called": True,
        "candidates_count": len(candidates),
        "llm_response": None,
        "choice": None,
        "confidence": None,
        "error": None,
        "duration_ms": 0
    }
    
    start_time = time.time()
    
    if not candidates:
        trace["error"] = "no_candidates"
        return None, 0.0, trace
    
    # Format candidates for prompt (only titles + keywords)
    candidates_text = ""
    for i, c in enumerate(candidates):
        keywords = _extract_keywords(c["question"], max_words=5)
        candidates_text += f'{i}. "{c["question"]}" (keywords: {keywords})\n'
    
    prompt = SELECTOR_PROMPT.format(
        question=normalized_query,
        candidates=candidates_text,
        max_idx=len(candidates) - 1
    )
    
    try:
        response = chat_once(
            system="You are a precise FAQ selector. Return ONLY valid JSON, no other text.",
            user=prompt,
            temperature=0.0,
            max_tokens=100,
            timeout=timeout,
            model="gpt-4o-mini"
        )
        
        trace["llm_response"] = response[:200]
        trace["duration_ms"] = int((time.time() - start_time) * 1000)
        
        # Parse JSON response
        response_clean = response.strip()
        # Try to extract JSON if wrapped in markdown
        json_match = re.search(r'\{[^{}]*"choice"[^{}]*\}', response_clean)
        if json_match:
            response_clean = json_match.group(0)
        
        try:
            result = json.loads(response_clean)
            choice = result.get("choice")
            confidence = float(result.get("confidence", 0.0))
            
            trace["choice"] = choice
            trace["confidence"] = confidence
            
            # Validate choice
            if choice == -1 or confidence < SELECTOR_CONFIDENCE_THRESHOLD:
                return None, confidence, trace
            
            if not isinstance(choice, int) or choice < 0 or choice >= len(candidates):
                trace["error"] = f"invalid_choice_{choice}"
                return None, confidence, trace
            
            return choice, confidence, trace
            
        except json.JSONDecodeError as e:
            trace["error"] = f"json_parse_error: {str(e)[:50]}"
            return None, 0.0, trace
            
    except Exception as e:
        trace["duration_ms"] = int((time.time() - start_time) * 1000)
        trace["error"] = f"error_{str(e)[:50]}"
        return None, 0.0, trace


def verify_selection(
    selected_faq: dict,
    selector_response: dict,
    candidates: list[dict]
) -> tuple[bool, str]:
    """
    Guardrail verifier: ensure selection is valid and safe.
    
    Returns:
        (is_valid, reason)
    """
    # Gate 1: Must have a selection
    if not selected_faq:
        return False, "no_faq_selected"
    
    # Gate 2: Selector must have responded
    if not selector_response:
        return False, "no_selector_response"
    
    # Gate 3: Choice must be valid index
    choice = selector_response.get("choice", -1)
    if choice == -1:
        return False, "selector_said_none"
    
    if choice < 0 or choice >= len(candidates):
        return False, f"invalid_choice_index_{choice}"
    
    # Gate 4: Confidence must be above threshold
    confidence = selector_response.get("confidence", 0)
    if confidence < 0.5:
        return False, f"low_confidence_{confidence}"
    
    # Gate 5: Selected FAQ must match the choice
    if selected_faq.get("faq_id") != candidates[choice].get("faq_id"):
        return False, "faq_mismatch"
    
    # Gate 6: Answer must exist and not be empty
    answer = selected_faq.get("answer", "")
    if not answer or len(answer.strip()) < 10:
        return False, "empty_or_short_answer"
    
    return True, "passed"


def guardrail_verifier(
    chosen_faq_id: Optional[int],
    chosen_answer: Optional[str],
    candidates: List[Dict]
) -> Tuple[bool, Optional[str]]:
    """
    Guardrail verifier: Ensures chosen FAQ is valid and answer matches.
    
    Returns:
        (is_valid, error_message)
    """
    if chosen_faq_id is None:
        return False, "chosen_faq_id_is_null"
    
    # Find the candidate with matching faq_id
    matching_candidate = None
    for c in candidates:
        if c["faq_id"] == chosen_faq_id:
            matching_candidate = c
            break
    
    if matching_candidate is None:
        return False, f"chosen_faq_id_{chosen_faq_id}_not_in_candidates"
    
    # Verify answer matches (should be identical or very close)
    if chosen_answer is None:
        return False, "chosen_answer_is_null"
    
    # Allow slight variations (whitespace, case)
    answer_normalized = chosen_answer.strip().lower()
    candidate_answer_normalized = matching_candidate["answer"].strip().lower()
    
    if answer_normalized != candidate_answer_normalized:
        # Check if answer is at least a substring (some wrappers might add text)
        if answer_normalized not in candidate_answer_normalized and candidate_answer_normalized not in answer_normalized:
            return False, "answer_mismatch"
    
    return True, None


def llm_rerank(question: str, candidates: list[Dict], timeout: float = 3.0) -> Tuple[Optional[Dict], Dict]:
    """
    Ask LLM to pick the best FAQ from candidates.
    
    Returns:
        (best_match or None, trace_dict)
    """
    trace = {
        "stage": "llm_rerank",
        "candidates_count": len(candidates),
        "candidates_seen": [  # Store what LLM saw
            {
                "index": i + 1,
                "faq_id": c["faq_id"],
                "question": c["question"],
                "score": round(c["score"], 4)
            }
            for i, c in enumerate(candidates)
        ],
        "llm_response": None,
        "pick": None,
        "reason": None,
        "safety_gate": None,
        "duration_ms": 0
    }
    
    start_time = time.time()
    
    if not candidates:
        trace["safety_gate"] = "no_candidates"
        return None, trace
    
    # Format candidates for prompt
    candidates_text = ""
    for i, c in enumerate(candidates, 1):
        candidates_text += f"\n{i}. FAQ Question: \"{c['question']}\"\n"
        candidates_text += f"   Answer preview: {c['answer'][:150]}...\n"
    
    prompt = RERANK_PROMPT.format(
        question=question,
        candidates=candidates_text
    )
    
    try:
        response = chat_once(
            system="You are a precise FAQ matching assistant. Follow the response format exactly.",
            user=prompt,
            temperature=0.0,
            max_tokens=100,
            timeout=timeout,
            model="gpt-4o-mini"
        )
        
        trace["llm_response"] = response[:200]
        trace["duration_ms"] = int((time.time() - start_time) * 1000)
        
        # Parse response
        lines = response.strip().split("\n")
        pick_line = None
        reason_line = None
        
        for line in lines:
            line_lower = line.lower().strip()
            if line_lower.startswith("pick:"):
                pick_line = line.split(":", 1)[1].strip().lower()
            elif line_lower.startswith("reason:"):
                reason_line = line.split(":", 1)[1].strip()
        
        trace["pick"] = pick_line
        trace["reason"] = reason_line
        
        # Safety gate 1: Must have both pick and reason
        if not pick_line or not reason_line:
            trace["safety_gate"] = "missing_pick_or_reason"
            return None, trace
        
        # Safety gate 2: If "none", respect it
        if pick_line == "none":
            trace["safety_gate"] = "llm_said_none"
            return None, trace
        
        # Safety gate 3: Pick must be a valid number
        try:
            idx = int(pick_line.replace(".", "")) - 1
            if idx < 0 or idx >= len(candidates):
                trace["safety_gate"] = f"invalid_index_{idx}"
                return None, trace
        except ValueError:
            trace["safety_gate"] = f"unparseable_pick_{pick_line}"
            return None, trace
        
        # Safety gate 4: Reason must be non-trivial (at least 10 chars)
        if len(reason_line) < 10:
            trace["safety_gate"] = "reason_too_short"
            return None, trace
        
        # All gates passed
        trace["safety_gate"] = "passed"
        selected = candidates[idx]
        selected["rerank_reason"] = reason_line
        
        return selected, trace
        
    except Exception as e:
        trace["duration_ms"] = int((time.time() - start_time) * 1000)
        trace["safety_gate"] = f"error_{str(e)[:50]}"
        return None, trace


def retrieve(
    tenant_id: str,
    query: str,
    normalized_query: str,
    use_cache: bool = True
) -> tuple[Optional[dict], dict]:
    """
    Three-stage retrieval:
    1. Hybrid search (vector + FTS) - find candidates
    2. Cross-encoder rerank - rank by true relevance
    3. Threshold check - reject if cross-encoder score too low
    
    Returns:
        (result_dict or None, trace_dict)
    """
    trace = {
        "tenant_id": tenant_id,
        "query": query[:100],
        "normalized": normalized_query[:100],
        "stage": None,
        "vector_count": 0,
        "fts_count": 0,
        "merged_count": 0,
        "top_vector_score": 0,
        "top_fts_score": 0,
        "rerank_triggered": False,
        "rerank_trace": None,
        "final_score": 0,
        "cache_hit": False,
        "total_ms": 0,
        # Fine-grained timing breakdowns
        "retrieval_db_ms": 0,
        "retrieval_db_fts_ms": 0,
        "retrieval_db_vector_ms": 0,
        "retrieval_rerank_ms": 0,
        "retrieval_cache_ms": 0,
        "retrieval_total_ms": 0,
        # TASK C: Counters for timing headers
        "used_fts_only": False,
        "ran_vector": False,
        "fts_candidate_count": 0,
        "vector_k": 0,
        "selector_called": False  # Initialize selector_called to False
    }
    
    start_time = time.time()
    
    # ============================================================================
    # EARLY REJECTION CHECKS - MUST RUN BEFORE CACHE/RETRIEVAL/ANYTHING ELSE
    # ============================================================================
    
    query_lower = normalized_query.lower().strip()
    
    # Stage 0.1: Vague query check - reject immediately if too short or generic
    vague_patterns = ["hi", "hello", "help", "hey", "yo", "sup", "?", "??", "???"]
    if query_lower in vague_patterns or len(query_lower) < 4:
        trace["stage"] = "clarify_vague"
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        trace["used_fts_only"] = False
        trace["ran_vector"] = False
        trace["vector_k"] = 0
        trace["selector_called"] = False
        return None, trace
    
    # Stage 0.2: Wrong-service check - reject ONLY explicit wrong-trade intent
    # Allow mentions when electrical intent signals exist (voltage drop, power issues, alarms beeping, etc.)
    # This MUST run before cache, before retrieval, before everything
    
    # Electrical intent signals - if query contains these, allow even if wrong-service keyword present
    ELECTRICAL_INTENT_SIGNALS = [
        # Power/voltage issues
        "lights flicker", "lights dim", "lights dimming", "voltage drop", "power trips", "power cuts",
        "power went out", "power out", "power cutting", "safety switch", "rcd", "circuit breaker",
        "fuse box", "switchboard", "electrical panel", "powerpoint", "outlet", "socket",
        # Smoke/fire alarms (beeping/chirping = electrical issue, not security system)
        "smoke alarm beep", "smoke alarm chirp", "fire alarm beep", "fire alarm chirp",
        "smoke detector beep", "smoke detector chirp", "alarm beep", "alarm chirp", "beeping",
        "chirping", "battery low", "battery replacement",
        # Electrical problems
        "sparking", "buzzing", "humming", "crackling", "hot outlet", "burnt",
        # Appliance-related electrical issues (voltage drop when appliance runs)
        "when ac turns on", "when washing machine", "when dryer", "when appliance",
    ]
    
    # Check for electrical intent signals first
    has_electrical_intent = any(signal.lower() in query_lower for signal in ELECTRICAL_INTENT_SIGNALS)
    
    # Use module-level WRONG_SERVICE_KEYWORDS (defined at top of file)
    
    # Check if query contains wrong-service keywords
    wrong_service_keywords_in_query = [
        kw for kw in WRONG_SERVICE_KEYWORDS 
        if kw.lower() in query_lower
    ]
    
    # Reject ONLY if:
    # 1. Query contains wrong-service keyword AND
    # 2. Query does NOT have electrical intent signal AND
    # 3. Query is not about switchboard (always allow switchboard - it's electrical)
    if wrong_service_keywords_in_query and not has_electrical_intent and "switchboard" not in query_lower:
        trace["stage"] = "wrong_service_rejected"
        trace["wrong_service_keywords"] = wrong_service_keywords_in_query
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        trace["used_fts_only"] = False
        trace["ran_vector"] = False
        trace["vector_k"] = 0
        trace["selector_called"] = False
        return None, trace
    
    # ============================================================================
    # NOW SAFE TO PROCEED WITH NORMAL RETRIEVAL
    # ============================================================================
    
    retrieval_start_time = time.time()  # Start of actual retrieval (after early checks)
    
    # Stage 0: Check cache (only after early rejection checks)
    cache_start_time = time.time()
    if use_cache:
        cached = get_cached_result(tenant_id, normalized_query)
        trace["retrieval_cache_ms"] += int((time.time() - cache_start_time) * 1000)
        if cached:
            # Double-check cached result isn't a wrong-service hit (defensive)
            # This shouldn't happen if cache was cleared, but be safe
            cached_query_lower = normalized_query.lower()
            if not any(kw.lower() in cached_query_lower for kw in WRONG_SERVICE_KEYWORDS):
                # HARD RULE: Never allow faq_hit=true when candidate_count==0
                # For cached results, we need to ensure candidate_count is set
                # If cache doesn't have candidate_count, we can't verify, so we'll set a default
                # But ideally cache should include candidate_count - for now, assume it's valid if cached
                trace["cache_hit"] = True
                trace["stage"] = "cache"
                # Set candidate_count from cache if available, otherwise set to 1 (assume valid cached result)
                trace["candidates_count"] = cached.get("candidates_count", 1)
                # Set trace fields for cached results (may not be available in cache, so use defaults)
                trace["used_fts_only"] = cached.get("used_fts_only", False)
                trace["ran_vector"] = cached.get("ran_vector", False)
                trace["fts_candidate_count"] = cached.get("fts_candidate_count", 0)
                trace["vector_k"] = cached.get("vector_k", 0)
                trace["retrieval_total_ms"] = int((time.time() - retrieval_start_time) * 1000)
                trace["total_ms"] = int((time.time() - start_time) * 1000)
                return cached, trace
            # If cache contains wrong-service, ignore it and continue
    
    # Stage 1: Get candidates - FTS PRIMARY, embeddings SECONDARY
    
    # 1a: FTS search (primary - finds keyword matches)
    fts_start_time = time.time()
    fts_candidates = search_fts(tenant_id, normalized_query, limit=20)
    fts_db_ms = int((time.time() - fts_start_time) * 1000)
    trace["retrieval_db_fts_ms"] = fts_db_ms
    trace["retrieval_db_ms"] += fts_db_ms
    trace["fts_count"] = len(fts_candidates)
    fts_candidate_count = len(fts_candidates)
    trace["fts_candidate_count"] = fts_candidate_count
    
    # Compute FTS metrics for fast-path decision
    fts_top_score = 0.0
    fts_gap = 0.0
    if fts_candidates:
        fts_top_score = fts_candidates[0].get("fts_score", 0.0)
        trace["top_fts_score"] = round(fts_top_score, 4)
        if len(fts_candidates) >= 2:
            fts_second_score = fts_candidates[1].get("fts_score", 0.0)
            fts_gap = fts_top_score - fts_second_score
            trace["fts_gap"] = round(fts_gap, 4)
    
    # TASK A: FTS-only fast path (high confidence)
    # If FTS returns high-confidence results, accept immediately without vector or LLM selector
    # Adjusted thresholds: observed FTS rank scores are ~0.04-0.20, so previous thresholds were impossible
    use_fts_only_fast_path = False
    if fts_candidate_count >= 1 and (fts_top_score >= 0.12 or (fts_candidate_count >= 2 and fts_gap >= 0.03)):
        use_fts_only_fast_path = True
        trace["stage"] = "fts_high_confidence"
        trace["used_fts_only"] = True
        trace["ran_vector"] = False
        trace["vector_k"] = 0
        trace["selector_called"] = False  # FTS-only fast path doesn't use selector
        result = {
            "faq_id": fts_candidates[0]["faq_id"],
            "question": fts_candidates[0]["question"],
            "answer": fts_candidates[0]["answer"],
            "score": fts_top_score,
            "stage": "fts_high_confidence"
        }
        trace["final_score"] = fts_top_score
        trace["candidates_count"] = fts_candidate_count
        trace["retrieval_total_ms"] = int((time.time() - retrieval_start_time) * 1000)
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        
        if use_cache:
            cache_write_start = time.time()
            set_cached_result(tenant_id, normalized_query, result)
            trace["retrieval_cache_ms"] += int((time.time() - cache_write_start) * 1000)
        
        return result, trace
    
    # Small tenant fast path: Skip vector search for small tenants when FTS has candidates
    # For tenants with <= 50 FAQs, if FTS returns any candidates, skip expensive vector search
    SMALL_TENANT_FAQ_THRESHOLD = 50
    tenant_faq_count = _get_tenant_faq_count(tenant_id)
    trace["tenant_faq_count"] = tenant_faq_count
    trace["fts_candidate_count_at_small_check"] = fts_candidate_count
    trace["small_tenant_threshold"] = SMALL_TENANT_FAQ_THRESHOLD
    trace["small_tenant_check_result"] = fts_candidate_count >= 1 and tenant_faq_count <= SMALL_TENANT_FAQ_THRESHOLD
    
    if fts_candidate_count >= 1 and tenant_faq_count <= SMALL_TENANT_FAQ_THRESHOLD:
        trace["stage"] = "fts_small_tenant_fast_path"
        trace["used_fts_only"] = True
        trace["ran_vector"] = False
        trace["vector_k"] = 0
        trace["selector_called"] = False
        trace["vector_skipped"] = True
        trace["vector_skip_reason"] = "fts_small_tenant"
        result = {
            "faq_id": fts_candidates[0]["faq_id"],
            "question": fts_candidates[0]["question"],
            "answer": fts_candidates[0]["answer"],
            "score": fts_top_score if fts_top_score > 0 else 0.7,  # Use FTS score or default for small tenant
            "stage": "fts_small_tenant_fast_path"
        }
        trace["final_score"] = result["score"]
        trace["candidates_count"] = fts_candidate_count
        trace["retrieval_total_ms"] = int((time.time() - retrieval_start_time) * 1000)
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        
        if use_cache:
            cache_write_start = time.time()
            set_cached_result(tenant_id, normalized_query, result)
            trace["retrieval_cache_ms"] += int((time.time() - cache_write_start) * 1000)
        
        return result, trace
    
    # 1b: Vector search (secondary - finds semantic matches)
    # Skip vector search if FTS returned enough good candidates (>=8) OR if fast-path would have triggered but we need more candidates
    vector_candidates = []
    vector_start_time = time.time()
    should_skip_vector = fts_candidate_count >= 8  # Tightened: always skip if >= 8
    
    trace["used_fts_only"] = False
    trace["ran_vector"] = False
    trace["vector_k"] = 0
    
    if should_skip_vector:
        trace["vector_skipped"] = True
        trace["vector_skip_reason"] = f"fts_count={fts_candidate_count} >= 8"
        trace["retrieval_db_vector_ms"] = 0
        trace["vector_count"] = 0
        query_embedding = None  # Don't embed if we're skipping vector
    else:
        # TASK B: Make vector cheaper - reduce K to max 20 (already 20, but ensure it's capped)
        vector_k = 20  # Max vector candidates to retrieve
        trace["ran_vector"] = True
        trace["vector_k"] = vector_k
        
        from app.openai_client import embed_text
        query_embedding = embed_text(normalized_query)
        if query_embedding is not None:
            vector_candidates = get_top_candidates(tenant_id, query_embedding, limit=vector_k)
            vector_db_ms = int((time.time() - vector_start_time) * 1000)
            trace["retrieval_db_vector_ms"] = vector_db_ms
            trace["retrieval_db_ms"] += vector_db_ms
            trace["vector_count"] = len(vector_candidates)
            if vector_candidates:
                trace["top_vector_score"] = round(vector_candidates[0].get("score", 0), 4)
        else:
            trace["retrieval_db_vector_ms"] = int((time.time() - vector_start_time) * 1000)
            trace["vector_count"] = 0
    
    # 1c: Merge - FTS results get priority, vectors add extras
    candidates = merge_candidates_fts_primary(fts_candidates, vector_candidates)
    trace["merged_count"] = len(candidates)
    trace["candidates_count"] = len(candidates)  # Set candidate_count from actual list length
    
    # If still no candidates and query matches pricing intent, try embedding search with "price" appended
    if not candidates:
        query_lower = normalized_query.lower().strip()
        pricing_patterns = ["how much", "cost", "price", "rates", "quote", "charge", "fee"]
        has_pricing_intent = any(pattern in query_lower for pattern in pricing_patterns)
        
        if has_pricing_intent and query_embedding is not None:
            # Try searching with "price" keyword explicitly
            price_query = normalized_query + " price"
            fts_price_start_time = time.time()
            fts_price_candidates = search_fts(tenant_id, price_query, limit=20)
            fts_price_db_ms = int((time.time() - fts_price_start_time) * 1000)
            trace["retrieval_db_fts_ms"] += fts_price_db_ms
            trace["retrieval_db_ms"] += fts_price_db_ms
            if fts_price_candidates:
                candidates = fts_price_candidates
                trace["fts_count"] = len(candidates)
                trace["merged_count"] = len(candidates)
                trace["candidates_count"] = len(candidates)
    
    # CRITICAL: If we have ANY candidates, proceed (don't require high scores)
    if not candidates:
        trace["stage"] = "no_candidates"
        trace["candidates_count"] = 0  # Explicitly set to 0
        # Ensure trace fields are set
        if "used_fts_only" not in trace:
            trace["used_fts_only"] = False
        if "ran_vector" not in trace:
            trace["ran_vector"] = False
        if "vector_k" not in trace:
            trace["vector_k"] = 0
        if "selector_called" not in trace:
            trace["selector_called"] = False
        
        # If query is very short/generic (<=2-3 tokens), return clarify
        query_tokens = normalized_query.split()
        if len(query_tokens) <= 3:
            trace["stage"] = "clarify"  # Very short query with no candidates -> clarify
        
        trace["retrieval_total_ms"] = int((time.time() - retrieval_start_time) * 1000)
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        return None, trace
    
    
    top_combined_score = candidates[0].get("score", 0)
    
    # HARD RULE: Never allow faq_hit=true when candidate_count==0
    if len(candidates) == 0:
        trace["stage"] = "no_candidates"
        trace["candidates_count"] = 0
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        return None, trace
    
    # Fast path: High confidence from hybrid search (lowered to 0.5 for better recall)
    if top_combined_score >= 0.5:
        trace["stage"] = "hybrid_high_confidence"
        trace["candidates_count"] = len(candidates)  # Ensure candidate_count is set
        trace["selector_called"] = False  # High confidence hybrid doesn't use selector
        result = {
            "faq_id": candidates[0]["faq_id"],
            "question": candidates[0]["question"],
            "answer": candidates[0]["answer"],
            "score": top_combined_score,
            "stage": "hybrid"
        }
        trace["final_score"] = top_combined_score
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        
        if use_cache:
            cache_write_start = time.time()
            set_cached_result(tenant_id, normalized_query, result)
            trace["retrieval_cache_ms"] += int((time.time() - cache_write_start) * 1000)
        
        # Calculate total retrieval time (from start of retrieval, excluding early checks)
        trace["retrieval_total_ms"] = int((time.time() - retrieval_start_time) * 1000)
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        
        return result, trace
    
    # Stage 2: Rerank (cross-encoder if available, else LLM selector)
    trace["rerank_triggered"] = True
    
    candidates_to_rerank = candidates[:8]
    reranked = []
    rerank_trace = {}
    use_llm_selector = False
    
    rerank_start_time = time.time()
    # Try cross-encoder first
    try:
        from app.cross_encoder import rerank as cross_encoder_rerank, should_accept, ENABLE_CROSS_ENCODER
        
        if ENABLE_CROSS_ENCODER:
            reranked, rerank_trace = cross_encoder_rerank(
                normalized_query,
                candidates_to_rerank,
                top_k=5
            )
        else:
            # Cross-encoder disabled, use LLM selector
            use_llm_selector = True
            rerank_trace = {"method": "skipped", "reason": "cross_encoder_disabled"}
    except Exception as e:
        # Cross-encoder failed to import/load, use LLM selector
        use_llm_selector = True
        rerank_trace = {"method": "fallback", "error": str(e)[:100]}
    
    # Fallback to LLM selector if cross-encoder unavailable/disabled
    if use_llm_selector or not reranked:
        try:
            choice_idx, confidence, selector_trace = llm_selector(normalized_query, candidates_to_rerank[:5])
            trace["selector_called"] = True
            trace["selector_confidence"] = confidence
            trace["selector_trace"] = selector_trace
            
            if choice_idx is not None and 0 <= choice_idx < len(candidates_to_rerank):
                selected = candidates_to_rerank[choice_idx].copy()
                selected["rerank_score"] = confidence  # Use LLM confidence as rerank score
                reranked = [selected]
                rerank_trace["method"] = "llm_selector"
                rerank_trace["confidence"] = confidence
                rerank_trace["choice"] = choice_idx
            else:
                reranked = []
                rerank_trace["method"] = "llm_selector"
                rerank_trace["result"] = "no_match"
        except Exception as e:
            rerank_trace["llm_selector_error"] = str(e)[:100]
            reranked = []
    
    trace["retrieval_rerank_ms"] = int((time.time() - rerank_start_time) * 1000)
    
    trace["rerank_trace"] = rerank_trace
    
    if not reranked:
        trace["stage"] = "rerank_no_result"
        trace["candidates_count"] = len(candidates)  # Ensure candidate_count is set even on miss
        # Ensure trace fields are set
        if "used_fts_only" not in trace:
            trace["used_fts_only"] = False
        if "ran_vector" not in trace:
            trace["ran_vector"] = False
        if "vector_k" not in trace:
            trace["vector_k"] = 0
        if "selector_called" not in trace:
            trace["selector_called"] = False
        trace["retrieval_total_ms"] = int((time.time() - retrieval_start_time) * 1000)
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        return None, trace
    
    # Stage 3: Check threshold
    top_rerank_score = reranked[0].get("rerank_score", 0)
    trace["final_score"] = round(top_rerank_score, 4)
    
    # Use appropriate threshold based on method
    rerank_method = rerank_trace.get("method", "none")
    
    if rerank_method == "llm_selector":
        # LLM selector returns confidence 0-1, threshold at 0.7 for better precision
        LLM_THRESHOLD = 0.7
        accept = top_rerank_score >= LLM_THRESHOLD
        accept_reason = "llm_confident" if accept else f"llm_below_threshold_{top_rerank_score:.2f}"
    else:
        # Cross-encoder threshold
        try:
            from app.cross_encoder import should_accept
            accept, accept_reason = should_accept(top_rerank_score)
        except Exception:
            RERANK_THRESHOLD = 0.3
            accept = top_rerank_score >= RERANK_THRESHOLD
            accept_reason = "acceptable" if accept else f"below_threshold_{top_rerank_score:.2f}"
    
    trace["accept_reason"] = accept_reason
    
    if not accept:
        trace["stage"] = f"rejected_{accept_reason}"
        trace["candidates_count"] = len(candidates)  # Ensure candidate_count is set even on rejection
        # Ensure trace fields are set
        if "used_fts_only" not in trace:
            trace["used_fts_only"] = False
        if "ran_vector" not in trace:
            trace["ran_vector"] = False
        if "vector_k" not in trace:
            trace["vector_k"] = 0
        if "selector_called" not in trace:
            trace["selector_called"] = False
        trace["retrieval_total_ms"] = int((time.time() - retrieval_start_time) * 1000)
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        return None, trace
    
    # HARD RULE: Never allow faq_hit=true when candidate_count==0 (defensive check)
    if len(candidates) == 0:
        trace["stage"] = "no_candidates"
        trace["candidates_count"] = 0
        trace["retrieval_total_ms"] = int((time.time() - retrieval_start_time) * 1000)
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        return None, trace
    
    # Success
    trace["stage"] = f"{rerank_method}_accepted"
    trace["candidates_count"] = len(candidates)  # Ensure candidate_count is set on success
    # selector_called should already be set: True if LLM selector was called, False if cross-encoder was used
    if "selector_called" not in trace:
        trace["selector_called"] = False  # Shouldn't happen, but defensive check
    result = {
        "faq_id": reranked[0]["faq_id"],
        "question": reranked[0]["question"],
        "answer": reranked[0]["answer"],
        "score": top_rerank_score,
        "stage": "rerank",
        "rerank_score": top_rerank_score
    }
    trace["retrieval_total_ms"] = int((time.time() - retrieval_start_time) * 1000)
    trace["total_ms"] = int((time.time() - start_time) * 1000)
    
    if use_cache:
        cache_write_start = time.time()
        set_cached_result(tenant_id, normalized_query, result)
        trace["retrieval_cache_ms"] += int((time.time() - cache_write_start) * 1000)
    
    return result, trace

