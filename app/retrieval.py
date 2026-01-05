from pgvector import Vector
from .db import get_conn

THETA = 0.82
DELTA = 0.08


def retrieve_faq_answer(tenant_id: str, query_embedding):
    """
    Returns: (hit: bool, answer: str|None, score: float|None, delta: float|None, top_faq_id: int|None)

    Acceptance logic:
      - If top_score < THETA => miss
      - If top_score >= THETA:
          * If runner-up is same faq_id => accept (not ambiguous)
          * Else require (top_score - runner_up_score) >= DELTA
    """
    tenant_id = (tenant_id or "").strip()
    if not tenant_id or query_embedding is None:
        return (False, None, None, None, None)

    qv = Vector(query_embedding)

    sql = """
    SELECT fi.id AS faq_id, fi.answer AS answer, (1 - (fv.variant_embedding <=> %s)) AS score
    FROM faq_variants fv
    JOIN faq_items fi ON fi.id = fv.faq_id
    WHERE fi.tenant_id = %s
      AND fi.enabled = true
      AND fi.is_staged = false
      AND fv.enabled = true
    ORDER BY fv.variant_embedding <=> %s
    LIMIT 30
    """

    with get_conn() as conn:
        rows = conn.execute(sql, (qv, tenant_id, qv)).fetchall()

    if not rows:
        return (False, None, None, None, None)

    top_faq_id, top_answer, top_score = rows[0]
    top_faq_id = int(top_faq_id)
    top_answer = str(top_answer)
    top_score = float(top_score)

    # Find runner-up row (the second row), if it exists
    runner_up_score = None
    runner_up_faq_id = None
    if len(rows) >= 2:
        runner_up_faq_id = int(rows[1][0])
        runner_up_score = float(rows[1][2])

    # Must clear THETA first
    if top_score < THETA:
        delta = None if runner_up_score is None else (top_score - runner_up_score)
        return (False, None, top_score, delta, top_faq_id)

    # If we don't even have a runner-up, accept
    if runner_up_score is None:
        return (True, top_answer, top_score, top_score, top_faq_id)

    delta = top_score - runner_up_score

    # If the tie is within the same FAQ, accept (not ambiguous)
    if runner_up_faq_id == top_faq_id:
        return (True, top_answer, top_score, delta, top_faq_id)

    # Otherwise require separation
    hit = delta >= DELTA
    return (hit, top_answer if hit else None, top_score, delta, top_faq_id)


def get_top_faq_candidates(tenant_id: str, query_embedding, limit: int = 5) -> list[dict]:
    """
    Get top FAQ candidates with their scores for disambiguation.
    Returns list of {faq_id, question, answer, score}.
    """
    if not tenant_id or query_embedding is None:
        return []
    
    qv = Vector(query_embedding)
    
    sql = """
    SELECT DISTINCT ON (fi.id)
        fi.id AS faq_id, 
        fi.question, 
        fi.answer,
        (1 - (fv.variant_embedding <=> %s)) AS score
    FROM faq_variants fv
    JOIN faq_items fi ON fi.id = fv.faq_id
    WHERE fi.tenant_id = %s
      AND fi.enabled = true
      AND fv.enabled = true
      AND (fi.is_staged = false OR fi.is_staged IS NULL)
    ORDER BY fi.id, fv.variant_embedding <=> %s
    """
    
    with get_conn() as conn:
        # Get best score per FAQ
        rows = conn.execute(sql, (qv, tenant_id, qv)).fetchall()
    
    if not rows:
        return []
    
    # Sort by score descending and limit
    candidates = [
        {
            "faq_id": int(row[0]),
            "question": str(row[1]),
            "answer": str(row[2]),
            "score": float(row[3])
        }
        for row in rows
    ]
    candidates.sort(key=lambda x: x["score"], reverse=True)
    
    return candidates[:limit]
