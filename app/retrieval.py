from typing import Optional, Tuple
from pgvector import Vector
from .db import get_conn

THETA = 0.82
DELTA = 0.08

def retrieve_faq_answer(tenant_id: str, query_embedding) -> Tuple[bool, Optional[str], Optional[float], Optional[float]]:
    """
    Returns: (hit: bool, answer: str|None, score: float|None, delta: float|None)
    score is cosine similarity ~= 1 - cosine_distance
    """
    tenant_id = (tenant_id or "").strip()
    if not tenant_id or query_embedding is None:
        return (False, None, None, None)

    qv = Vector(query_embedding)

    sql = """
    SELECT fi.answer, (1 - (fv.variant_embedding <=> %s)) AS score
    FROM faq_variants fv
    JOIN faq_items fi ON fi.id = fv.faq_id
    WHERE fi.tenant_id = %s
      AND fi.enabled = true
      AND fv.enabled = true
    ORDER BY fv.variant_embedding <=> %s
    LIMIT 2
    """

    with get_conn() as conn:
        rows = conn.execute(sql, (qv, tenant_id, qv)).fetchall()

    if not rows:
        return (False, None, None, None)

    ans1, score1 = rows[0]
    ans1 = (ans1 or "").strip()
    score1 = float(score1)

    ans2 = ""
    score2 = 0.0
    if len(rows) > 1:
        ans2, score2 = rows[1]
        ans2 = (ans2 or "").strip()
        score2 = float(score2)

    delta = score1 - score2

    # Fix A: if top two rows resolve to the same answer text, treat as unambiguous.
    same_answer = bool(ans1) and bool(ans2) and (ans1 == ans2)

    hit = (score1 >= THETA) and ((delta >= DELTA) or same_answer)
    return (hit, ans1 if ans1 else None, score1, float(delta))
