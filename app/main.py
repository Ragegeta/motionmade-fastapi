from __future__ import annotations

import re
import os
from typing import List, Optional, Set

from fastapi import FastAPI, Header, HTTPException, Response, Request

from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
from pgvector import Vector

from .settings import settings
from .guardrails import FALLBACK, violates_general_safety, classify_fact_domain, is_capability_question, is_logistics_question
from .openai_client import embed_text, chat_once
from .retrieval import retrieve_faq_answer
from .db import get_conn
from .triage import triage_input, CLARIFY_RESPONSE
from .normalize import normalize_message
from .splitter import split_intents


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


def is_rewrite_safe(rewritten: str, original: str) -> bool:
    if not rewritten:
        return False
    rw = _extract_fact_tokens(rewritten)
    ot = _extract_fact_tokens(original)
    return len(rw - ot) == 0


# -----------------------------
# FastAPI setup + DB schema
# -----------------------------
app = FastAPI()


@app.middleware("http")
async def add_release_headers(request: Request, call_next):
    resp = await call_next(request)
    git_sha = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_SHA") or "unknown"
    release = os.getenv("RENDER_GIT_BRANCH") or os.getenv("RELEASE") or "unknown"
    resp.headers["x-git-sha"] = git_sha
    resp.headers["x-release"] = release
    return resp


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
    resp.headers["X-Git-Sha"] = os.getenv("RENDER_GIT_COMMIT","")
    resp.headers["X-Entrypoint"] = "app.main"


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


def _replica_fact_domain(msg: str) -> str:
    """
    Tenant-agnostic routing helper (platform invariant).
    - Never answer capability questions from general chat.
    - Treat logistics/ops questions as business so retrieval/FAQ can answer.
    - Otherwise, defer to existing business domain classification.
    """
    t = (msg or "").lower()

    # Let obvious general-knowledge prompts stay general.
    if re.search(r"\b(why|explain|what is|what's|how does|define)\b", t):
        return "none"

    # Universal capability phrasing -> business
    if re.search(r"\b(can|could)\s+(you|u|ya)\b", t) or re.search(r"\bdo\s+(you|u|ya)\b", t) or "do you offer" in t or "are you able to" in t:
        return "capability"

    # Universal logistics/ops -> business
    if any(k in t for k in [
        "water and power", "need water", "need power", "water", "power", "electricity", "power point", "powerpoint",
        "are you mobile", "mobile", "come to me", "come to my", "do you come", "can you come", "do you travel", "travel to",
        "parking", "visitor parking", "keys", "key", "access", "gate code", "lockbox"
    ]):
        return "other"

    # Otherwise defer to existing classifier if present
    try:
        return classify_fact_domain(msg)  # noqa: F821
    except Exception:
        return "none"


def _init_debug_headers(resp: Response, tenant_id: str, msg: str) -> str:
    _set_common_headers(resp, tenant_id)

    domain = _replica_fact_domain(msg)
    resp.headers["X-Fact-Domain"] = domain
    resp.headers["X-Fact-Gate-Hit"] = "true" if domain != "none" else "false"

    resp.headers["X-Faq-Hit"] = "false"
    resp.headers["X-Debug-Branch"] = "error"
    return domain


@app.on_event("startup")
def _startup():
    with get_conn() as conn:
        conn.execute(SCHEMA_SQL)
        conn.commit()


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


def _should_fallback_after_miss(msg: str, domain: str) -> bool:
    t = (msg or "").strip()
    if not t:
        return True

    # Hard rule: capability phrasing must NEVER go to general chat
    if is_capability_question(t):
        return True

    # Logistics questions should not be answered by general chat either
    if is_logistics_question(t):
        return True

    # If the legacy gate thinks it's business, keep it safe
    if domain != "none":
        return True

    # Extra cheap business signals (universal)
    low = t.lower()
    if any(k in low for k in ["price", "pricing", "cost", "how much", "quote", "availability", "book", "booking", "pay", "payment"]):
        return True

    return False


@app.post("/api/v2/generate-quote-reply")
def generate_quote_reply(req: QuoteRequest, resp: Response):
    tenant_id = (req.tenantId or "").strip()
    msg = (req.customerMessage or "").strip()

    # === TRIAGE ===
    triage_result, should_continue = triage_input(msg)
    resp.headers["X-Triage-Result"] = triage_result
    
    if not should_continue:
        resp.headers["X-Debug-Branch"] = "clarify"
        resp.headers["X-Faq-Hit"] = "false"
        payload = _base_payload()
        payload["replyText"] = CLARIFY_RESPONSE
        return payload

    # === NORMALIZE ===
    normalized_msg = normalize_message(msg)
    resp.headers["X-Normalized-Input"] = (normalized_msg or "")[:80]

    # === SPLIT INTENTS ===
    intents = split_intents(normalized_msg)
    if not intents:
        intents = [normalized_msg] if normalized_msg else [msg]
    resp.headers["X-Intent-Count"] = str(len(intents))
    
    # Use first intent for retrieval (multi-intent handling comes later)
    primary_query = intents[0] if intents else normalized_msg or msg

    domain = _init_debug_headers(resp, tenant_id, primary_query)
    payload = _base_payload()

    # -----------------------------
    # Retrieval-first (ALWAYS runs)
    # -----------------------------
    try:
        # 1) Original retrieval
        q_emb = embed_text(primary_query)
        hit, ans, score, delta, faq_id = retrieve_faq_answer(tenant_id, q_emb)

        if score is not None:
            resp.headers["X-Retrieval-Score"] = str(score)
        if delta is not None:
            resp.headers["X-Retrieval-Delta"] = str(delta)
        if faq_id is not None:
            resp.headers["X-Top-Faq-Id"] = str(faq_id)

        if hit and ans:
            resp.headers["X-Debug-Branch"] = "fact_hit"
            resp.headers["X-Faq-Hit"] = "true"
            payload["replyText"] = str(ans).strip()
            return payload

        # 2) Miss -> rewrite for retrieval only
        resp.headers["X-Debug-Branch"] = "fact_rewrite_try"

        if "X-Retrieval-Score" in resp.headers:
            resp.headers["X-Retrieval-Score-Raw"] = resp.headers["X-Retrieval-Score"]
        if "X-Retrieval-Delta" in resp.headers:
            resp.headers["X-Retrieval-Delta-Raw"] = resp.headers["X-Retrieval-Delta"]
        if "X-Top-Faq-Id" in resp.headers:
            resp.headers["X-Top-Faq-Id-Raw"] = resp.headers["X-Top-Faq-Id"]

        rewrite = ""
        try:
            system = (
                "Rewrite the user message into a short FAQ-style query (max 12 words). "
                "Preserve the meaning. Do not add or change any facts. "
                "Do NOT invent numbers, prices, times, policies, or inclusions. "
                "Output only the rewritten query text with no quotes or explanation."
            )
            rewrite = chat_once(system, f"Original customer message: {msg}", temperature=0.0).strip()
        except Exception:
            rewrite = ""

        if rewrite:
            resp.headers["X-Fact-Rewrite"] = rewrite[:80]
            if not is_rewrite_safe(rewrite, msg):
                rewrite = ""

        if rewrite:
            rw_emb = embed_text(rewrite)
            rw_hit, rw_ans, rw_score, rw_delta, rw_faq_id = retrieve_faq_answer(tenant_id, rw_emb)

            if rw_score is not None:
                resp.headers["X-Retrieval-Score"] = str(rw_score)
            if rw_delta is not None:
                resp.headers["X-Retrieval-Delta"] = str(rw_delta)
            if rw_faq_id is not None:
                resp.headers["X-Top-Faq-Id"] = str(rw_faq_id)

            if rw_hit and rw_ans:
                resp.headers["X-Debug-Branch"] = "fact_rewrite_hit"
                resp.headers["X-Faq-Hit"] = "true"
                payload["replyText"] = str(rw_ans).strip()
                return payload

    except Exception:
        # If retrieval pipeline errors, fail safe
        resp.headers["X-Debug-Branch"] = "error"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = FALLBACK
        return payload

    # -----------------------------
    # Retrieval miss -> decide fallback vs general
    # -----------------------------
    if _should_fallback_after_miss(msg, domain):
        resp.headers["X-Debug-Branch"] = "fact_miss"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = FALLBACK
        return payload

    # -----------------------------
    # General chat (only truly non-business)
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

@app.get("/api/health")
def health():
    git_sha = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_SHA") or "unknown"
    release = os.getenv("RENDER_GIT_BRANCH") or os.getenv("RELEASE") or "unknown"
    return {"ok": True, "gitSha": git_sha, "release": release}

