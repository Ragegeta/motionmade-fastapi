from __future__ import annotations

import re
from typing import List, Optional, Set, Tuple

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict

from pgvector import Vector

from .settings import settings
from .guardrails import FALLBACK, violates_general_safety
from .openai_client import embed_text, chat_once
from .retrieval import retrieve_faq_answer
from .db import get_conn


# -----------------------------
# Deterministic fact gate
# -----------------------------

def fact_domain(text: str) -> str:
    """
    Returns one of:
      pricing|time|inclusions|policy|payment|travel|service_area|other|none
    """
    if not text:
        return "none"

    t = text.lower().strip()

    # service_area (explicit keywords only; not generic "do you")
    if re.search(r"\b(service area|service areas|coverage)\b", t):
        return "service_area"
    if re.search(r"\b(area|areas|suburb|suburbs|location|locations|radius|within)\b", t):
        return "service_area"
    if re.search(r"\b(where do you(?:\s+\w+){0,2})\b", t) or re.search(r"\b(do you service|where do you service)\b", t):
        return "service_area"
    if re.search(r"\b(northside|southside|cbd)\b", t):
        return "service_area"

    # pricing
    if re.search(r"\b(price|pricing|cost|quote|how much|\$|dollars?|aud)\b", t):
        return "pricing"

    # time
    if re.search(r"\b(time|duration|how long|hours?|hrs?|minutes?|mins?|days?)\b", t):
        return "time"

    # inclusions
    if re.search(r"\b(included|inclusions|include|what(?:'s| is) included|checklist)\b", t):
        return "inclusions"

    # policy
    if re.search(r"\b(cancel|cancellation|resched|refund|policy|policies|late fee|fee)\b", t):
        return "policy"

    # payment
    if re.search(r"\b(pay|payment|card|invoice|bank transfer|eft|cash)\b", t):
        return "payment"

    # travel
    if re.search(r"\b(travel|parking|toll|distance|surcharge)\b", t):
        return "travel"

    # “Do you / can you …” service capability questions -> treat as business fact (unknown => fallback)
    # (Not triggered by “do you” alone; requires an action/service keyword.)
    if re.search(r"\b(do you|can you)\b", t) and re.search(
        r"\b(clean|cleaning|bond|end of lease|vacate|deep|standard|oven|fridge|windows?|laundry|linen|ironing|polish|steam|wash|remove|stain|grout|carpet|upholstery|blinds?|balcony|mould|mold|pressure)\b",
        t,
    ):
        return "other"

    return "none"


def is_fact_question(text: str) -> bool:
    return fact_domain(text) != "none"


# -----------------------------
# Rewrite safety (numbers/units must not be invented)
# -----------------------------

def _extract_fact_tokens(text: str) -> Set[str]:
    if not text:
        return set()
    t = text.lower()
    toks = set(re.findall(r"\$?\d+(?:\.\d{1,2})?", t))
    toks |= set(re.findall(r"\b(aud|dollars?|hrs?|hours?|mins?|minutes?|days?)\b", t))
    return toks


def is_rewrite_safe(rewritten: str, fact_text: str) -> bool:
    if not rewritten:
        return False
    rw = _extract_fact_tokens(rewritten)
    ft = _extract_fact_tokens(fact_text)
    # If rewrite introduced any new number/unit tokens => unsafe
    return len(rw - ft) == 0


# -----------------------------
# FastAPI setup + DB schema
# -----------------------------

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tenants (
  id TEXT PRIMARY KEY,
  name TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS faq_items (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  embedding vector(1536) NULL,
  enabled BOOLEAN NOT NULL DEFAULT true,
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (tenant_id, question)
);

CREATE INDEX IF NOT EXISTS faq_tenant_enabled_idx ON faq_items(tenant_id, enabled);

CREATE TABLE IF NOT EXISTS faq_variants (
  id BIGSERIAL PRIMARY KEY,
  faq_id BIGINT NOT NULL REFERENCES faq_items(id) ON DELETE CASCADE,
  variant_question TEXT NOT NULL,
  variant_embedding vector(1536) NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT true,
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS faq_variants_faq_id_idx ON faq_variants(faq_id);
CREATE INDEX IF NOT EXISTS faq_variants_embedding_idx
ON faq_variants USING ivfflat (variant_embedding vector_cosine_ops)
WITH (lists = 100);
"""


def _set_common_headers(resp: Response, tenant_id: str):
    resp.headers["X-Build"] = settings.BUILD_ID
    resp.headers["X-Served-By"] = "fastapi"
    resp.headers["X-TenantId"] = tenant_id or ""


def _base_payload():
    return {
        "replyText": "",
        "lowEstimate": None,
        "highEstimate": None,
        "includedServices": [],
        "suggestedTimes": [],
        "estimateText": "",
        "jobSummaryShort": "",
        "disclaimer": "Prices are estimates and may vary based on condition and access.",
    }


def _init_debug_headers(resp: Response, tenant_id: str, msg: str):
    _set_common_headers(resp, tenant_id)

    domain = fact_domain(msg)
    resp.headers["X-Fact-Gate-Hit"] = "true" if domain != "none" else "false"
    resp.headers["X-Fact-Domain"] = domain

    # always present
    resp.headers["X-Faq-Hit"] = "false"
    resp.headers["X-Debug-Branch"] = "error"  # overwritten on success paths
    return domain


@app.on_event("startup")
def _startup():
    with get_conn() as conn:
        conn.execute(SCHEMA_SQL)
        conn.commit()


@app.get("/api/health")
def health(resp: Response):
    _set_common_headers(resp, "")
    resp.headers["X-Debug-Branch"] = "general_ok"
    resp.headers["X-Fact-Gate-Hit"] = "false"
    resp.headers["X-Fact-Domain"] = "none"
    resp.headers["X-Faq-Hit"] = "false"
    return "ok"


class FaqItem(BaseModel):
    question: str
    answer: str
    variants: Optional[List[str]] = None


class QuoteRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    tenantId: str
    customerMessage: str


@app.put("/admin/tenant/{tenantId}/faqs")
def put_faqs(
    tenantId: str,
    items: List[FaqItem],
    resp: Response,
    authorization: str = Header(default=""),
):
    _set_common_headers(resp, tenantId)

    if authorization != f"Bearer {settings.ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        count = 0
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (tenantId, tenantId),
            )

            # Replace-all semantics (deterministic)
            conn.execute("DELETE FROM faq_items WHERE tenant_id=%s", (tenantId,))

            for it in items:
                q = (it.question or "").strip()
                a = (it.answer or "").strip()
                if not q or not a:
                    continue

                emb_q = embed_text(q)
                row = conn.execute(
                    "INSERT INTO faq_items (tenant_id, question, answer, embedding, enabled) "
                    "VALUES (%s,%s,%s,%s,true) RETURNING id",
                    (tenantId, q, a, Vector(emb_q)),
                ).fetchone()
                faq_id = row[0]

                # Always include canonical question + any variants (dedup, normalized)
                raw_variants = it.variants or []
                seen = set()
                variants: List[str] = []
                for v in [q, *raw_variants]:
                    vv = (v or "").strip()
                    if not vv:
                        continue
                    key = vv.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    variants.append(vv)

                for vq in variants:
                    v_emb = embed_text(vq)
                    conn.execute(
                        "INSERT INTO faq_variants (faq_id, variant_question, variant_embedding, enabled) "
                        "VALUES (%s,%s,%s,true)",
                        (faq_id, vq, Vector(v_emb)),
                    )

                count += 1

            conn.commit()

        resp.headers["X-Debug-Branch"] = "general_ok"
        resp.headers["X-Faq-Hit"] = "false"
        return {"tenantId": tenantId, "count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"admin_upload_failed: {e!s}")


@app.post("/api/v2/generate-quote-reply")
def generate_quote_reply(req: QuoteRequest, resp: Response):
    tenant_id = (req.tenantId or "").strip()
    msg = (req.customerMessage or "").strip()

    domain = _init_debug_headers(resp, tenant_id, msg)
    payload = _base_payload()

    # -----------------------------
    # Fact branch
    # -----------------------------
    if domain != "none":
        try:
            q_emb = embed_text(msg)
            hit, ans, score, delta = retrieve_faq_answer(tenant_id, q_emb)

            # If retrieval ran: expose score/delta even on miss
            if score is not None:
                resp.headers["X-Retrieval-Score"] = str(score)
            if delta is not None:
                resp.headers["X-Retrieval-Delta"] = str(delta)

            if hit and ans:
                resp.headers["X-Debug-Branch"] = "fact_hit"
                resp.headers["X-Faq-Hit"] = "true"

                fact_text = str(ans).strip()

                # Optional AI rewrite, but must be provably safe
                rewritten = ""
                try:
                    system = (
                        "Rewrite the customer reply using ONLY the provided fact text. "
                        "Do not add, remove, or change any facts, numbers, prices, policies, inclusions, or conditions. "
                        "Keep it short, clear, and professional."
                    )
                    rewritten = chat_once(
                        system,
                        f"Customer question: {msg}\n\nFact text: {fact_text}",
                        temperature=0.2,
                    ).strip()
                except Exception:
                    rewritten = ""

                payload["replyText"] = rewritten if is_rewrite_safe(rewritten, fact_text) else fact_text
                return payload

            # Fact gate hit but retrieval didn't accept
            resp.headers["X-Debug-Branch"] = "fact_miss"
            resp.headers["X-Faq-Hit"] = "false"
            payload["replyText"] = FALLBACK
            return payload

        except Exception:
            resp.headers["X-Debug-Branch"] = "error"
            resp.headers["X-Faq-Hit"] = "false"
            payload["replyText"] = FALLBACK
            return payload

    # -----------------------------
    # General branch (ONLY non-fact)
    # -----------------------------
    try:
        system = (
            "Reply in one short paragraph. Do not ask follow-up questions. "
            "Do not state or imply any business facts like prices, durations, policies, inclusions, or fees. "
            f"If the user asks anything that sounds like business specifics, reply exactly: {FALLBACK}"
        )
        reply = chat_once(system, msg, temperature=0.6)
    except Exception:
        resp.headers["X-Debug-Branch"] = "error"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = FALLBACK
        return payload

    if violates_general_safety(reply):
        resp.headers["X-Debug-Branch"] = "general_fallback"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = FALLBACK
        return payload

    resp.headers["X-Debug-Branch"] = "general_ok"
    resp.headers["X-Faq-Hit"] = "false"
    payload["replyText"] = reply
    return payload
