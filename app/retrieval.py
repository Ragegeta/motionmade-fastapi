from collections import defaultdict
from typing import Any, Dict, List, Tuple, Optional

from pgvector import Vector
from .db import get_conn

THETA = 0.82
DELTA = 0.08

def retrieve_faq_answer(tenant_id: str, query_embedding):
    """
    Returns: (hit: bool, answer: str|None, score: float|None, delta: float|None)

    Key change: we de-duplicate by FAQ (faq_id), so "top2 tie" caused by multiple variants
    of the SAME FAQ no longer kills the hit.
    """
    tenant_id = (tenant_id or "").strip()
    if not tenant_id or query_embedding is None:
        return (False, None, None, None)

    qv = Vector(query_embedding)

    # Pull more rows, because we will collapse them down to unique faq_id
    sql = """
    SELECT
      fi.id AS faq_id,
      fi.answer AS answer,
      (1 - (fv.variant_embedding <=> %s)) AS score
    FROM faq_variants fv
    JOIN faq_items fi ON fi.id = fv.faq_id
    WHERE fi.tenant_id = %s
      AND fi.enabled = true
      AND fv.enabled = true
    ORDER BY fv.variant_embedding <=> %s
    LIMIT 12
    """

    with get_conn() as conn:
        rows = conn.execute(sql, (qv, tenant_id, qv)).fetchall()

    if not rows:
        return (False, None, None, None)

    # Best score per FAQ id (not per variant row)
    best_by_faq: Dict[int, Tuple[str, float]] = {}
    for faq_id, ans, score in rows:
        s = float(score)
        fid = int(faq_id)
        if fid not in best_by_faq or s > best_by_faq[fid][1]:
            best_by_faq[fid] = (str(ans), s)

    # Sort unique FAQs by their best score
    ranked: List[Tuple[str, float]] = sorted(best_by_faq.values(), key=lambda x: x[1], reverse=True)

    top_ans, top_score = ranked[0]
    if len(ranked) == 1:
        # Only one unique FAQ is present in the candidates -> accept if score is strong
        hit = top_score >= THETA
        delta = 1.0
        return (hit, top_ans if hit else None, top_score, delta)

    second_score = ranked[1][1]
    delta = float(top_score - second_score)

    hit = (top_score >= THETA) and (delta >= DELTA)
    return (hit, top_ans if hit else None, top_score, delta)
