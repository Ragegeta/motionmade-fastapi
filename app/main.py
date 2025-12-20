from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Tuple

from .settings import settings
from .guardrails import FALLBACK, is_fact_question, violates_general_safety
from .openai_client import embed_text, embed_texts, chat_once
from .retrieval import retrieve_faq_answer
from .db import get_conn
from pgvector import Vector


def _extract_fact_tokens(text: str) -> set[str]:
    import re
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
    return len(rw - ft) == 0


app = FastAPI()

# CORS for browser-based frontend calls
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

-- Variant questions for robust matching (answer remains in faq_items)
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
        # 1) Normalize + dedupe
        clean: List[Tuple[str, str, List[str]]] = []
        for it in items:
            q = (it.question or "").strip()
            a = (it.answer or "").strip()
            if not q or not a:
                continue

            raw_variants = it.variants or []
            seen = set()
            variants: List[str] = []
            # include canonical question as a variant too
            for v in [q, *raw_variants]:
                vv = (v or "").strip().lower()
                if vv and vv not in seen:
                    seen.add(vv)
                    variants.append(vv)

            clean.append((q, a, variants))

        # 2) Batch embed: FAQ questions
        faq_questions = [q for (q, _, _) in clean]
        faq_embs = embed_texts(faq_questions) if faq_questions else []

        # 3) Batch embed: all variants in one go
        # flatten (faq_index, variant_text) so we can map embeddings back
        variant_pairs: List[Tuple[int, str]] = []
        for i, (_, _, vars_) in enumerate(clean):
            for v in vars_:
                variant_pairs.append((i, v))

        variant_texts = [v for (_, v) in variant_pairs]
        variant_embs = embed_texts(variant_texts) if variant_texts else []

        # 4) Write to DB
        count = 0
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (tenantId, tenantId),
            )

            # Replace-all semantics (simple + deterministic)
            # Deleting faq_items cascades faq_variants.
            conn.execute("DELETE FROM faq_items WHERE tenant_id=%s", (tenantId,))

            # Insert each FAQ (fast now — no network calls inside this loop)
            faq_ids: List[int] = []
            for (q, a, _), emb_q in zip(clean, faq_embs):
                row = conn.execute(
                    "INSERT INTO faq_items (tenant_id, question, answer, embedding, enabled) "
                    "VALUES (%s,%s,%s,%s,true) RETURNING id",
                    (tenantId, q, a, Vector(emb_q)),
                ).fetchone()
                faq_ids.append(int(row[0]))
                count += 1

            # Insert variants (also fast now)
            for (idx, vq), v_emb in zip(variant_pairs, variant_embs):
                conn.execute(
                    "INSERT INTO faq_variants (faq_id, variant_question, variant_embedding, enabled) "
                    "VALUES (%s,%s,%s,true)",
                    (faq_ids[idx], vq, Vector(v_emb)),
                )

            conn.commit()

        resp.headers["X-Debug-Branch"] = "admin_ok"
        resp.headers["X-Faq-Hit"] = "false"
        return {"tenantId": tenantId, "count": count}

    except Exception as e:
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

                fact_text = ans
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
                    )
                    rewritten = (rewritten or "").strip()
                except Exception:
                    rewritten = ""

                if not is_rewrite_safe(rewritten, fact_text):
                    payload["replyText"] = fact_text
                    resp.headers["X-Debug-Branch"] = "fact_db_only"
                else:
                    payload["replyText"] = rewritten
                    resp.headers["X-Debug-Branch"] = "fact_ai_rewrite"

                return payload

            resp.headers["X-Debug-Branch"] = "fact_fallback"
            resp.headers["X-Faq-Hit"] = "false"
            if score is not None:
                resp.headers["X-Retrieval-Score"] = str(score)
            if delta is not None:
                resp.headers["X-Retrieval-Delta"] = str(delta)
            payload["replyText"] = FALLBACK
            return payload

        except Exception:
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
