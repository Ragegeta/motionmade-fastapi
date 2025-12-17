import psycopg
from pgvector.psycopg import register_vector
from pgvector import Vector

from .settings import settings
from .openai_client import embed_text


def retrieve_faq(tenant_id: str, question: str, top_k: int = 3):
    """
    Returns: (hit: bool, answer: str|None, score: float|None, delta: float|None)
    Never raises. If anything fails -> (False, None, None, None)
    """
    try:
        emb = embed_text(question)
        if not emb or not isinstance(emb, (list, tuple)):
            return (False, None, None, None)

        v = Vector(list(emb))

        sql = """
        SELECT
            answer,
            1 - (embedding <=> %s) AS score
        FROM faq_items
        WHERE tenant_id = %s
          AND enabled = true
          AND embedding IS NOT NULL
        ORDER BY embedding <=> %s
        LIMIT %s
        """

        with psycopg.connect(settings.DATABASE_URL) as conn:
            register_vector(conn)
            rows = conn.execute(sql, (v, tenant_id, v, top_k)).fetchall()

        if not rows:
            return (False, None, None, None)

        top1_answer, top1_score = rows[0][0], float(rows[0][1])

        if len(rows) >= 2:
            top2_score = float(rows[1][1])
            delta = top1_score - top2_score
        else:
            # If only one result exists, treat as clearly best
            delta = 1.0

        return (True, top1_answer, top1_score, float(delta))

    except Exception:
        # Never 500 from fact branch again
        return (False, None, None, None)