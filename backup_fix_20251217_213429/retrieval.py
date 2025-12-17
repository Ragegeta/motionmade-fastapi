from pgvector import Vector
from .db import get_conn

THETA = 0.82
DELTA = 0.08

def retrieve_faq_answer(tenant_id: str, query_embedding):
    """
    Returns: (hit: bool, answer: str|None, score: float|None, delta: float|None)
    Never throws for empty DB.
    """
    if not tenant_id or query_embedding is None:
        return (False, None, None, None)

    qv = Vector(query_embedding)

    sql = """
    SELECT question, answer, (1 - (embedding <=> %s)) AS score
    FROM faq_items
    WHERE tenant_id = %s
      AND enabled = true
      AND embedding IS NOT NULL
    ORDER BY embedding <=> %s
    LIMIT 3
    """

    with get_conn() as conn:
        rows = conn.execute(sql, (qv, tenant_id, qv)).fetchall()

    if not rows:
        return (False, None, None, None)

    top_q, top_a, top_score = rows[0]
    top2_score = rows[1][2] if len(rows) > 1 else 0.0

    top_score = float(top_score)
    top2_score = float(top2_score)
    delta = top_score - top2_score

    hit = (top_score >= THETA) and (delta >= DELTA)
    return (hit, top_a, top_score, float(delta))