from __future__ import annotations

import re
import os
import time
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

CREATE TABLE IF NOT EXISTS telemetry (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  query_text TEXT,
  normalized_text TEXT,
  intent_count INTEGER,
  debug_branch TEXT,
  faq_hit BOOLEAN,
  top_faq_id BIGINT,
  retrieval_score REAL,
  rewrite_triggered BOOLEAN,
  latency_ms INTEGER
);

CREATE INDEX IF NOT EXISTS telemetry_tenant_idx ON telemetry(tenant_id, created_at DESC);
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


def _log_telemetry(
    tenant_id: str,
    query_text: str,
    normalized_text: str,
    intent_count: int,
    debug_branch: str,
    faq_hit: bool,
    top_faq_id,
    retrieval_score,
    rewrite_triggered: bool,
    latency_ms: int
):
    """Log request telemetry for analytics. Fails silently."""
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO telemetry 
                   (tenant_id, query_text, normalized_text, intent_count, debug_branch, 
                    faq_hit, top_faq_id, retrieval_score, rewrite_triggered, latency_ms)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (tenant_id, (query_text or "")[:500], (normalized_text or "")[:500], intent_count, 
                 debug_branch, faq_hit, top_faq_id, retrieval_score, rewrite_triggered, latency_ms)
            )
            conn.commit()
    except Exception:
        pass  # Don't fail request if telemetry fails


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


@app.put("/api/v2/admin/tenant/{tenantId}/faqs")
def put_faqs_v2(
    tenantId: str,
    items: List[FaqItem],
    resp: Response,
    authorization: str = Header(default=""),
):
    """Admin FAQ upload endpoint (Cloudflare-compatible path)."""
    return put_faqs(tenantId, items, resp, authorization)


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
    _start_time = time.time()
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
        _latency_ms = int((time.time() - _start_time) * 1000)
        _log_telemetry(
            tenant_id=tenant_id,
            query_text=msg,
            normalized_text=msg,
            intent_count=0,
            debug_branch=resp.headers.get("X-Debug-Branch", "unknown"),
            faq_hit=resp.headers.get("X-Faq-Hit", "false") == "true",
            top_faq_id=int(resp.headers.get("X-Top-Faq-Id")) if resp.headers.get("X-Top-Faq-Id") else None,
            retrieval_score=float(resp.headers.get("X-Retrieval-Score")) if resp.headers.get("X-Retrieval-Score") else None,
            rewrite_triggered=resp.headers.get("X-Rewrite-Triggered", "false") == "true",
            latency_ms=_latency_ms
        )
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
            _latency_ms = int((time.time() - _start_time) * 1000)
            _log_telemetry(
                tenant_id=tenant_id,
                query_text=msg,
                normalized_text=normalized_msg,
                intent_count=int(resp.headers.get("X-Intent-Count", "1")),
                debug_branch=resp.headers.get("X-Debug-Branch", "unknown"),
                faq_hit=resp.headers.get("X-Faq-Hit", "false") == "true",
                top_faq_id=int(resp.headers.get("X-Top-Faq-Id")) if resp.headers.get("X-Top-Faq-Id") else None,
                retrieval_score=float(resp.headers.get("X-Retrieval-Score")) if resp.headers.get("X-Retrieval-Score") else None,
                rewrite_triggered=resp.headers.get("X-Rewrite-Triggered", "false") == "true",
                latency_ms=_latency_ms
            )
            return payload

        # 2) Miss -> rewrite for retrieval only
        resp.headers["X-Debug-Branch"] = "fact_rewrite_try"
        resp.headers["X-Rewrite-Triggered"] = "true"

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
                _latency_ms = int((time.time() - _start_time) * 1000)
                _log_telemetry(
                    tenant_id=tenant_id,
                    query_text=msg,
                    normalized_text=normalized_msg,
                    intent_count=int(resp.headers.get("X-Intent-Count", "1")),
                    debug_branch=resp.headers.get("X-Debug-Branch", "unknown"),
                    faq_hit=resp.headers.get("X-Faq-Hit", "false") == "true",
                    top_faq_id=int(resp.headers.get("X-Top-Faq-Id")) if resp.headers.get("X-Top-Faq-Id") else None,
                    retrieval_score=float(resp.headers.get("X-Retrieval-Score")) if resp.headers.get("X-Retrieval-Score") else None,
                    rewrite_triggered=resp.headers.get("X-Rewrite-Triggered", "false") == "true",
                    latency_ms=_latency_ms
                )
                return payload

    except Exception:
        # If retrieval pipeline errors, fail safe
        resp.headers["X-Debug-Branch"] = "error"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = FALLBACK
        _latency_ms = int((time.time() - _start_time) * 1000)
        _log_telemetry(
            tenant_id=tenant_id,
            query_text=msg,
            normalized_text=normalized_msg if 'normalized_msg' in locals() else msg,
            intent_count=int(resp.headers.get("X-Intent-Count", "1")),
            debug_branch=resp.headers.get("X-Debug-Branch", "unknown"),
            faq_hit=resp.headers.get("X-Faq-Hit", "false") == "true",
            top_faq_id=int(resp.headers.get("X-Top-Faq-Id")) if resp.headers.get("X-Top-Faq-Id") else None,
            retrieval_score=float(resp.headers.get("X-Retrieval-Score")) if resp.headers.get("X-Retrieval-Score") else None,
            rewrite_triggered=resp.headers.get("X-Rewrite-Triggered", "false") == "true",
            latency_ms=_latency_ms
        )
        return payload

    # -----------------------------
    # Retrieval miss -> decide fallback vs general
    # -----------------------------
    if _should_fallback_after_miss(msg, domain):
        resp.headers["X-Debug-Branch"] = "fact_miss"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = FALLBACK
        _latency_ms = int((time.time() - _start_time) * 1000)
        _log_telemetry(
            tenant_id=tenant_id,
            query_text=msg,
            normalized_text=normalized_msg,
            intent_count=int(resp.headers.get("X-Intent-Count", "1")),
            debug_branch=resp.headers.get("X-Debug-Branch", "unknown"),
            faq_hit=resp.headers.get("X-Faq-Hit", "false") == "true",
            top_faq_id=int(resp.headers.get("X-Top-Faq-Id")) if resp.headers.get("X-Top-Faq-Id") else None,
            retrieval_score=float(resp.headers.get("X-Retrieval-Score")) if resp.headers.get("X-Retrieval-Score") else None,
            rewrite_triggered=resp.headers.get("X-Rewrite-Triggered", "false") == "true",
            latency_ms=_latency_ms
        )
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
        _latency_ms = int((time.time() - _start_time) * 1000)
        _log_telemetry(
            tenant_id=tenant_id,
            query_text=msg,
            normalized_text=normalized_msg if 'normalized_msg' in locals() else msg,
            intent_count=int(resp.headers.get("X-Intent-Count", "1")),
            debug_branch=resp.headers.get("X-Debug-Branch", "unknown"),
            faq_hit=resp.headers.get("X-Faq-Hit", "false") == "true",
            top_faq_id=int(resp.headers.get("X-Top-Faq-Id")) if resp.headers.get("X-Top-Faq-Id") else None,
            retrieval_score=float(resp.headers.get("X-Retrieval-Score")) if resp.headers.get("X-Retrieval-Score") else None,
            rewrite_triggered=resp.headers.get("X-Rewrite-Triggered", "false") == "true",
            latency_ms=_latency_ms
        )
        return payload

    if violates_general_safety(reply):
        resp.headers["X-Debug-Branch"] = "general_fallback"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = FALLBACK
        _latency_ms = int((time.time() - _start_time) * 1000)
        _log_telemetry(
            tenant_id=tenant_id,
            query_text=msg,
            normalized_text=normalized_msg,
            intent_count=int(resp.headers.get("X-Intent-Count", "1")),
            debug_branch=resp.headers.get("X-Debug-Branch", "unknown"),
            faq_hit=resp.headers.get("X-Faq-Hit", "false") == "true",
            top_faq_id=int(resp.headers.get("X-Top-Faq-Id")) if resp.headers.get("X-Top-Faq-Id") else None,
            retrieval_score=float(resp.headers.get("X-Retrieval-Score")) if resp.headers.get("X-Retrieval-Score") else None,
            rewrite_triggered=resp.headers.get("X-Rewrite-Triggered", "false") == "true",
            latency_ms=_latency_ms
        )
        return payload

    resp.headers["X-Debug-Branch"] = "general_ok"
    resp.headers["X-Faq-Hit"] = "false"
    payload["replyText"] = reply
    _latency_ms = int((time.time() - _start_time) * 1000)
    _log_telemetry(
        tenant_id=tenant_id,
        query_text=msg,
        normalized_text=normalized_msg,
        intent_count=int(resp.headers.get("X-Intent-Count", "1")),
        debug_branch=resp.headers.get("X-Debug-Branch", "unknown"),
        faq_hit=resp.headers.get("X-Faq-Hit", "false") == "true",
        top_faq_id=int(resp.headers.get("X-Top-Faq-Id")) if resp.headers.get("X-Top-Faq-Id") else None,
        retrieval_score=float(resp.headers.get("X-Retrieval-Score")) if resp.headers.get("X-Retrieval-Score") else None,
        rewrite_triggered=resp.headers.get("X-Rewrite-Triggered", "false") == "true",
        latency_ms=_latency_ms
    )
    return payload

@app.get("/api/health")
def health():
    git_sha = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_SHA") or "unknown"
    release = os.getenv("RENDER_GIT_BRANCH") or os.getenv("RELEASE") or "unknown"
    return {"ok": True, "gitSha": git_sha, "release": release}


@app.get("/admin/tenant/{tenantId}/stats")
def get_tenant_stats(tenantId: str, resp: Response, authorization: str = Header(default="")):
    """Get telemetry stats for a tenant (last 24 hours)."""
    _set_common_headers(resp, tenantId)
    
    if authorization != f"Bearer {settings.ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    with get_conn() as conn:
        row = conn.execute("""
            SELECT 
                COUNT(*) as total_queries,
                COUNT(*) FILTER (WHERE faq_hit = true) as faq_hits,
                COUNT(*) FILTER (WHERE debug_branch = 'clarify') as clarify_count,
                COUNT(*) FILTER (WHERE debug_branch IN ('fact_miss', 'general_fallback')) as fallback_count,
                COUNT(*) FILTER (WHERE debug_branch = 'general_ok') as general_ok_count,
                COUNT(*) FILTER (WHERE rewrite_triggered = true) as rewrite_count,
                COALESCE(AVG(latency_ms)::integer, 0) as avg_latency_ms
            FROM telemetry 
            WHERE tenant_id = %s 
            AND created_at > now() - interval '24 hours'
        """, (tenantId,)).fetchone()
    
    total = row[0] or 1  # Avoid division by zero
    return {
        "tenant_id": tenantId,
        "period": "last_24_hours",
        "total_queries": row[0] or 0,
        "faq_hit_rate": round((row[1] or 0) / total, 3),
        "clarify_rate": round((row[2] or 0) / total, 3),
        "fallback_rate": round((row[3] or 0) / total, 3),
        "general_ok_rate": round((row[4] or 0) / total, 3),
        "rewrite_rate": round((row[5] or 0) / total, 3),
        "avg_latency_ms": row[6] or 0,
    }


@app.get("/api/v2/admin/tenant/{tenantId}/stats")
def get_tenant_stats_v2(tenantId: str, resp: Response, authorization: str = Header(default="")):
    """Admin telemetry stats endpoint (Cloudflare-compatible path)."""
    return get_tenant_stats(tenantId, resp, authorization)


@app.get("/debug/routes")
def debug_routes():
    """Debug endpoint to list registered routes. Only available when DEBUG=true."""
    if not settings.DEBUG:
        raise HTTPException(status_code=404, detail="Not found")
    
    routes = []
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                if method != "HEAD":  # Skip HEAD, it's implicit
                    routes.append({"method": method, "path": route.path})
    
    return {"routes": sorted(routes, key=lambda x: (x["path"], x["method"]))}

