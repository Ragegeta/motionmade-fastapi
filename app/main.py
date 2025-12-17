from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict
from typing import List

from .settings import settings
from .guardrails import FALLBACK, is_fact_question, violates_general_safety
from .openai_client import embed_text, chat_once
from .retrieval import retrieve_faq_answer
from .db import get_conn
from pgvector import Vector

app = FastAPI()

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

@app.on_event("startup")
def _startup():
    with get_conn() as conn:
        conn.execute(SCHEMA_SQL)
        conn.commit()

@app.get("/api/health")
def health(resp: Response):
    _set_common_headers(resp, "")
    return "ok"

class FaqItem(BaseModel):
    question: str
    answer: str

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
            conn.execute("DELETE FROM faq_items WHERE tenant_id=%s", (tenantId,))

            for it in items:
                q = (it.question or "").strip()
                a = (it.answer or "").strip()
                if not q or not a:
                    continue
                emb = embed_text(q)
                conn.execute(
                    "INSERT INTO faq_items (tenant_id, question, answer, embedding, enabled) VALUES (%s,%s,%s,%s,true)",
                    (tenantId, q, a, Vector(emb)),
                )
                count += 1

            conn.commit()

        resp.headers["X-Debug-Branch"] = "admin_ok"
        resp.headers["X-Faq-Hit"] = "false"
        return {"tenantId": tenantId, "count": count}
    except Exception as e:
        # Admin-only endpoint, OK to show error
        raise HTTPException(status_code=500, detail=f"admin_upload_failed: {e!s}")

@app.post("/api/v2/generate-quote-reply")
def generate_quote_reply(req: QuoteRequest, resp: Response):
    tenant_id = (req.tenantId or "").strip()
    msg = (req.customerMessage or "").strip()

    _set_common_headers(resp, tenant_id)
    payload = _base_payload()

    # Fact gate
    if is_fact_question(msg):
        try:
            q_emb = embed_text(msg)
            hit, ans, score, delta = retrieve_faq_answer(tenant_id, q_emb)

            if hit and ans:
                resp.headers["X-Debug-Branch"] = "fact_hit"
                resp.headers["X-Faq-Hit"] = "true"
                resp.headers["X-Retrieval-Score"] = str(score)
                resp.headers["X-Retrieval-Delta"] = str(delta)
                payload["replyText"] = ans
                return payload

            resp.headers["X-Debug-Branch"] = "fact_fallback"
            resp.headers["X-Faq-Hit"] = "false"
            if score is not None: resp.headers["X-Retrieval-Score"] = str(score)
            if delta is not None: resp.headers["X-Retrieval-Delta"] = str(delta)
            payload["replyText"] = FALLBACK
            return payload
        except Exception:
            # Never 500 for customers
            resp.headers["X-Debug-Branch"] = "fact_error_fallback"
            resp.headers["X-Faq-Hit"] = "false"
            payload["replyText"] = FALLBACK
            return payload

    # General branch
    try:
        system = (
            "Reply in one short paragraph. Do not ask follow-up questions. "
            "Do not state or imply any business facts like prices, durations, policies, inclusions, or fees. "
            f"If the user asks anything that sounds like business specifics, reply exactly: {FALLBACK}"
        )
        reply = chat_once(system, msg, temperature=0.6)
    except Exception:
        resp.headers["X-Debug-Branch"] = "general_error_fallback"
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