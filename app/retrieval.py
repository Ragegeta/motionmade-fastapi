from typing import Optional, Tuple, List
from pgvector import Vector
from .db import get_conn

THETA = 0.82
DELTA = 0.08

def retrieve_faq_answer(tenant_id: str, query_embedding):
    """
    Returns: (hit: bool, answer: str|None, score: float|None, delta: float|None)

    Fix A (real):
    - Pull more than 3 rows
    - Compute the "second best" score from a *different FAQ (or different answer)*
    - If only one distinct FAQ/answer exists, delta should not block a hit
    """
    tenant_id = (tenant_id or "").strip()
    if not tenant_id or query_embedding is None:
        return (False, None, None, None)

    qv = Vector(query_embedding)

    sql = """
    SELECT fi.id AS faq_id, fi.answer AS answer, (1 - (fv.variant_embedding <=> %s)) AS score
    FROM faq_variants fv
    JOIN faq_items fi ON fi.id = fv.faq_id
    WHERE fi.tenant_id = %s
      AND fi.enabled = true
      AND fv.enabled = true
    ORDER BY fv.variant_embedding <=> %s
    LIMIT 30
    """

    with get_conn() as conn:
        rows = conn.execute(sql, (qv, tenant_id, qv)).fetchall()

    if not rows:
        return (False, None, None, None)

    top_faq_id, top_answer, top_score = rows[0]
    top_faq_id = int(top_faq_id)
    top_answer = str(top_answer)
    top_score = float(top_score)

    # Find the best competing score from a *different* FAQ or at least different answer
    second_score = None
    for faq_id, ans, score in rows[1:]:
        faq_id = int(faq_id)
        ans = str(ans)
        s = float(score)
        if faq_id != top_faq_id and ans.strip() != top_answer.strip():
            second_score = s
            break

    # If there is no meaningful "second" competitor, don't let delta block the hit
    if second_score is None:
        delta = top_score
    else:
        delta = top_score - float(second_score)

    hit = (top_score >= THETA) and (delta >= DELTA)
    return (hit, top_answer, top_score, float(delta))