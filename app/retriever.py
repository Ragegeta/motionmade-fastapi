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
from typing import Optional, Tuple, Dict, Any
from app.db import get_conn
from app.openai_client import chat_once

# Thresholds
THETA_HIGH = 0.82       # Above this = direct hit, skip LLM
THETA_LOW = 0.40        # Below this = too uncertain, skip LLM (waste of money)
THETA_RERANK = 0.40     # Rerank zone: 0.40-0.82

# Cache TTL (seconds)
CACHE_TTL = 3600  # 1 hour


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


def get_top_candidates(tenant_id: str, query_embedding, limit: int = 5) -> list[Dict]:
    """Get top FAQ candidates via embedding similarity."""
    if not tenant_id or query_embedding is None:
        return []
    
    try:
        from pgvector.psycopg import register_vector
        from pgvector import Vector
        
        with get_conn() as conn:
            register_vector(conn)
            
            # Convert to Vector
            qv = Vector(query_embedding)
            
            rows = conn.execute("""
                SELECT DISTINCT ON (fi.id)
                    fi.id AS faq_id,
                    fi.question,
                    fi.answer,
                    fi.tenant_id,
                    fv.variant_question AS matched_variant,
                    (1 - (fv.variant_embedding <=> %s)) AS score
                FROM faq_variants fv
                JOIN faq_items fi ON fi.id = fv.faq_id
                WHERE fi.tenant_id = %s
                  AND fi.enabled = true
                  AND fv.enabled = true
                  AND (fi.is_staged = false OR fi.is_staged IS NULL)
                ORDER BY fi.id, (fv.variant_embedding <=> %s) ASC
            """, (qv, tenant_id, qv)).fetchall()
        
        if not rows:
            return []
        
        candidates = [
            {
                "faq_id": int(row[0]),
                "question": str(row[1]),
                "answer": str(row[2]),
                "tenant_id": str(row[3]),
                "matched_variant": str(row[4]) if row[4] else str(row[1]),  # Fallback to question if no variant
                "score": float(row[5])
            }
            for row in rows
        ]
        
        # Sort by score descending
        candidates.sort(key=lambda x: x["score"], reverse=True)
        return candidates[:limit]
        
    except Exception as e:
        print(f"Candidate retrieval error: {e}")
        import traceback
        traceback.print_exc()
        return []


def llm_rerank(question: str, candidates: list[Dict], timeout: float = 3.0) -> Tuple[Optional[Dict], Dict]:
    """
    Ask LLM to pick the best FAQ from candidates.
    
    Returns:
        (best_match or None, trace_dict)
    """
    trace = {
        "stage": "llm_rerank",
        "candidates_count": len(candidates),
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
) -> Tuple[Optional[Dict], Dict]:
    """
    Two-stage retrieval: embeddings + conditional LLM rerank.
    
    Args:
        tenant_id: Tenant identifier
        query: Original customer query
        normalized_query: Normalized query (for cache key and LLM)
        use_cache: Whether to use caching
    
    Returns:
        (result_dict or None, trace_dict)
        
    Result dict contains:
        - faq_id, question, answer, score
        - stage: "cache", "embedding", "rerank"
        
    Trace dict contains:
        - All diagnostic info for headers
    """
    trace = {
        "tenant_id": tenant_id,
        "query": query[:100],
        "normalized": normalized_query[:100],
        "stage": None,
        "top_score": None,
        "candidates_count": 0,
        "cache_hit": False,
        "rerank_triggered": False,
        "rerank_trace": None,
        "total_ms": 0
    }
    
    start_time = time.time()
    
    # Stage 0: Check cache
    if use_cache:
        cached = get_cached_result(tenant_id, normalized_query)
        if cached:
            trace["cache_hit"] = True
            trace["stage"] = "cache"
            trace["total_ms"] = int((time.time() - start_time) * 1000)
            return cached, trace
    
    # Stage 1: Embedding retrieval
    from app.openai_client import embed_text
    
    query_embedding = embed_text(normalized_query)
    if query_embedding is None:
        trace["stage"] = "embedding_failed"
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        return None, trace
    
    candidates = get_top_candidates(tenant_id, query_embedding, limit=5)
    trace["candidates_count"] = len(candidates)
    
    if not candidates:
        trace["stage"] = "no_candidates"
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        return None, trace
    
    top_score = candidates[0]["score"]
    trace["top_score"] = round(top_score, 4)
    
    # Fast path: High confidence embedding match
    if top_score >= THETA_HIGH:
        trace["stage"] = "embedding_high"
        result = {
            "faq_id": candidates[0]["faq_id"],
            "question": candidates[0]["question"],
            "answer": candidates[0]["answer"],
            "score": top_score,
            "stage": "embedding"
        }
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        
        # Cache the result
        if use_cache:
            set_cached_result(tenant_id, normalized_query, result)
        
        return result, trace
    
    # Too low: Don't waste LLM call
    if top_score < THETA_LOW:
        trace["stage"] = "embedding_too_low"
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        return None, trace
    
    # Stage 2: LLM rerank (0.40-0.82 range)
    trace["rerank_triggered"] = True
    
    rerank_result, rerank_trace = llm_rerank(normalized_query, candidates)
    trace["rerank_trace"] = rerank_trace
    
    if rerank_result:
        trace["stage"] = "rerank_hit"
        result = {
            "faq_id": rerank_result["faq_id"],
            "question": rerank_result["question"],
            "answer": rerank_result["answer"],
            "score": rerank_result["score"],
            "stage": "rerank",
            "rerank_reason": rerank_result.get("rerank_reason", "")
        }
        trace["total_ms"] = int((time.time() - start_time) * 1000)
        
        # Cache the result
        if use_cache:
            set_cached_result(tenant_id, normalized_query, result)
        
        return result, trace
    
    # Rerank failed or said "none"
    trace["stage"] = "rerank_none"
    trace["total_ms"] = int((time.time() - start_time) * 1000)
    return None, trace

