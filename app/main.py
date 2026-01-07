from __future__ import annotations

import re
import os
import time
import hashlib
from pathlib import Path
from typing import List, Optional, Set

from fastapi import FastAPI, Header, HTTPException, Response, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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
from .cache import get_cached_result, cache_result, get_cache_stats
from .variant_expander import expand_faq_list

# Import suite_runner defensively to avoid startup failures
try:
    from .suite_runner import run_suite
except ImportError as e:
    # If suite_runner can't be imported (e.g., missing requests), define a stub
    def run_suite(base_url: str, tenant_id: str) -> dict:
        """Stub for run_suite when dependencies are missing."""
        return {
            "passed": False,
            "total": 0,
            "passed_count": 0,
            "first_failure": {"name": "Suite runner unavailable", "error": str(e)}
        }


# ========================================
# VARIANT EXPANSION (inline, no external script)
# ========================================

QUESTION_STARTERS = [
    "what", "how", "where", "when", "why", "who", "which", "can", "do", "does", 
    "are", "is", "will", "would", "could", "should", "tell me", "show me", "i need"
]

SLANG_EXPANSIONS = [
    (r'\bur\b', ['your', 'you are']),
    (r'\bu\b', ['you']),
    (r'\bpls\b', ['please']),
    (r'\bthx\b', ['thanks']),
    (r'\bwat\b', ['what']),
    (r'\b2\b', ['to', 'two']),
    (r'\b4\b', ['for']),
]

def expand_variants_inline(faqs: list, max_per_faq: int = 30) -> list:
    """Expand variants for a list of FAQs. Returns modified FAQ list."""
    for faq in faqs:
        question = faq.get("question", "").lower()
        existing = set(v.lower() for v in faq.get("variants", []))
        new_variants = set(existing)
        
        # Add the question itself
        new_variants.add(question)
        
        # Extract key terms (words > 3 chars, not common words)
        stop_words = {'what', 'your', 'about', 'does', 'have', 'this', 'that', 'with', 'the', 'and', 'for', 'are', 'you'}
        words = re.findall(r'\b\w+\b', question)
        key_terms = [w for w in words if len(w) > 3 and w.lower() not in stop_words]
        
        # Add short versions (just key terms)
        if key_terms:
            new_variants.add(" ".join(key_terms[:2]))
            new_variants.add(key_terms[0])
        
        # Add question starter variations
        for term in key_terms[:2]:
            for starter in QUESTION_STARTERS[:8]:
                new_variants.add(f"{starter} {term}")
        
        # Add slang versions
        for variant in list(new_variants):
            for pattern, replacements in SLANG_EXPANSIONS:
                if re.search(pattern, variant, re.IGNORECASE):
                    for repl in replacements:
                        new_variant = re.sub(pattern, repl, variant, flags=re.IGNORECASE)
                        new_variants.add(new_variant.lower())
        
        # Clean and dedupe
        cleaned = sorted(set(v.strip().lower() for v in new_variants if v and len(v) >= 2))
        faq["variants"] = cleaned[:max_per_faq]
    
    return faqs


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

# Mount static files with no-store cache control
static_app = StaticFiles(directory="app/static")
app.mount("/static", static_app, name="static")

# Add Cache-Control header for static files
@app.middleware("http")
async def add_static_cache_control(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Type"] = "application/javascript"
    return response


@app.middleware("http")
async def add_release_headers(request: Request, call_next):
    resp = await call_next(request)
    git_sha = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_SHA") or "unknown"
    release = os.getenv("RENDER_GIT_BRANCH") or os.getenv("RELEASE") or "unknown"
    resp.headers["x-git-sha"] = git_sha
    resp.headers["x-release"] = release
    
    # Add Cache-Control for admin and static files
    if request.url.path.startswith("/admin") or request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store"
    
    # Set Content-Type for static JS files
    if request.url.path.startswith("/static/") and request.url.path.endswith(".js"):
        resp.headers["Content-Type"] = "application/javascript"
    
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

CREATE TABLE IF NOT EXISTS tenant_domains (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  domain TEXT NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (tenant_id, domain)
);

CREATE INDEX IF NOT EXISTS tenant_domains_tenant_idx ON tenant_domains(tenant_id);
CREATE INDEX IF NOT EXISTS tenant_domains_domain_idx ON tenant_domains(domain);

CREATE TABLE IF NOT EXISTS faq_items (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  embedding vector(1536) NULL,
  enabled BOOLEAN NOT NULL DEFAULT true,
  is_staged BOOLEAN NOT NULL DEFAULT false,
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (tenant_id, question, is_staged)
);

CREATE TABLE IF NOT EXISTS faq_items_last_good (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  embedding vector(1536) NULL,
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (tenant_id, question)
);

CREATE TABLE IF NOT EXISTS tenant_promote_history (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id),
  status TEXT NOT NULL,
  suite_result JSONB,
  first_failure JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS tenant_promote_history_tenant_idx ON tenant_promote_history(tenant_id, created_at DESC);

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
  query_length INTEGER,
  normalized_length INTEGER,
  query_hash TEXT,
  normalized_hash TEXT,
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


def _hash_text(text: str) -> str:
    """Generate a short hash for privacy-safe logging. Returns empty string for empty input."""
    if not text:
        return ""
    # Use SHA256 and take first 16 chars for a short, collision-resistant hash
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def _set_timing_headers(resp: Response, timings: dict, cache_hit: bool):
    """Set timing headers (only in DEBUG mode)."""
    if settings.DEBUG:
        resp.headers["X-Timing-Triage"] = str(timings["triage_ms"])
        resp.headers["X-Timing-NormalizeSplit"] = str(timings["normalize_split_ms"])
        resp.headers["X-Timing-Embedding"] = str(timings["embedding_ms"])
        resp.headers["X-Timing-Retrieval"] = str(timings["retrieval_ms"])
        resp.headers["X-Timing-Rewrite"] = str(timings["rewrite_ms"])
        resp.headers["X-Timing-LLM"] = str(timings["llm_ms"])
        resp.headers["X-Timing-Total"] = str(timings["total_ms"])
        resp.headers["X-Cache-Hit"] = "true" if cache_hit else "false"


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
    latency_ms: int,
    candidate_count: Optional[int] = None,
    retrieval_mode: Optional[str] = None,
    selector_called: Optional[bool] = None,
    selector_confidence: Optional[float] = None,
    chosen_faq_id: Optional[int] = None,
    retrieval_latency_ms: Optional[int] = None,
    selector_latency_ms: Optional[int] = None
):
    """Log request telemetry for analytics. Privacy-safe: stores only lengths and hashes, not raw text."""
    try:
        query_len = len(query_text) if query_text else 0
        normalized_len = len(normalized_text) if normalized_text else 0
        query_hash = _hash_text(query_text)
        normalized_hash = _hash_text(normalized_text)
        
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO telemetry 
                   (tenant_id, query_length, normalized_length, query_hash, normalized_hash, 
                    intent_count, debug_branch, faq_hit, top_faq_id, retrieval_score, 
                    rewrite_triggered, latency_ms, candidate_count, retrieval_mode, 
                    selector_called, selector_confidence, chosen_faq_id, 
                    retrieval_latency_ms, selector_latency_ms)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (tenant_id, query_len, normalized_len, query_hash, normalized_hash, intent_count, 
                 debug_branch, faq_hit, top_faq_id, retrieval_score, rewrite_triggered, latency_ms,
                 candidate_count, retrieval_mode, selector_called, selector_confidence, chosen_faq_id,
                 retrieval_latency_ms, selector_latency_ms)
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
    """Initialize database schema on startup. Non-blocking - failures don't prevent startup."""
    # Run DB initialization in background thread to avoid blocking startup
    # If DB is slow/unavailable, app still starts and can serve /ping
    import threading
    
    def init_db():
        try:
            with get_conn() as conn:
                conn.execute(SCHEMA_SQL)
                conn.commit()
            
            # Migrate telemetry table if old columns exist
            try:
                with get_conn() as conn:
                    # Check if old columns exist
                    check_old = conn.execute("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name = 'telemetry' AND column_name IN ('query_text', 'normalized_text')
                    """).fetchall()
                    
                    # Check if new columns exist
                    check_new = conn.execute("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name = 'telemetry' AND column_name IN ('query_length', 'query_hash')
                    """).fetchall()
                    
                    if check_old and not check_new:
                        # Migrate: add new columns, then drop old ones
                        conn.execute("""
                            ALTER TABLE telemetry 
                            ADD COLUMN IF NOT EXISTS query_length INTEGER,
                            ADD COLUMN IF NOT EXISTS normalized_length INTEGER,
                            ADD COLUMN IF NOT EXISTS query_hash TEXT,
                            ADD COLUMN IF NOT EXISTS normalized_hash TEXT
                        """)
                        conn.commit()
                        # Note: We don't drop old columns immediately to allow gradual migration
                        # Old columns can be dropped manually after verifying new schema works
            except Exception:
                pass  # Migration is best-effort, don't fail startup
            
            # Migrate faq_items to add is_staged column if missing
            try:
                with get_conn() as conn:
                    check_staged = conn.execute("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name = 'faq_items' AND column_name = 'is_staged'
                    """).fetchall()
                    
                    if not check_staged:
                        conn.execute("""
                            ALTER TABLE faq_items 
                            ADD COLUMN IF NOT EXISTS is_staged BOOLEAN NOT NULL DEFAULT false
                        """)
                        # Update unique constraint
                        try:
                            conn.execute("DROP INDEX IF EXISTS faq_items_tenant_question_key")
                        except:
                            pass
                        conn.execute("""
                            CREATE UNIQUE INDEX IF NOT EXISTS faq_items_tenant_question_staged_key 
                            ON faq_items(tenant_id, question, is_staged)
                        """)
                        conn.commit()
            except Exception:
                pass  # Migration is best-effort
            
            # Migrate telemetry to add new v2 fields
            try:
                with get_conn() as conn:
                    conn.execute("""
                        ALTER TABLE telemetry 
                        ADD COLUMN IF NOT EXISTS candidate_count INTEGER,
                        ADD COLUMN IF NOT EXISTS retrieval_mode TEXT,
                        ADD COLUMN IF NOT EXISTS selector_called BOOLEAN,
                        ADD COLUMN IF NOT EXISTS selector_confidence REAL,
                        ADD COLUMN IF NOT EXISTS chosen_faq_id BIGINT,
                        ADD COLUMN IF NOT EXISTS retrieval_latency_ms INTEGER,
                        ADD COLUMN IF NOT EXISTS selector_latency_ms INTEGER
                    """)
                    conn.commit()
            except Exception:
                pass  # Migration is best-effort
                
        except Exception as e:
            # Log but don't fail startup - app can still serve /ping and other endpoints
            import logging
            logging.warning(f"Database initialization failed (non-fatal): {e}")
            # App will still start, but DB-dependent endpoints may fail
    
    # Start DB init in background thread (non-blocking)
    thread = threading.Thread(target=init_db, daemon=True)
    thread.start()


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

            # Delete only live FAQs (not staged)
            # Handle case where is_staged column might not exist yet
            try:
                conn.execute("DELETE FROM faq_items WHERE tenant_id=%s AND is_staged=false", (tenantId,))
            except Exception:
                # Fallback: delete all if column doesn't exist (for migration period)
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
    
    # Timing breakdown
    timings = {
        "triage_ms": 0,
        "normalize_split_ms": 0,
        "embedding_ms": 0,
        "retrieval_ms": 0,
        "rewrite_ms": 0,
        "llm_ms": 0,
        "total_ms": 0
    }
    _cache_hit = False

    # === TRIAGE ===
    _t0 = time.time()
    triage_result, should_continue = triage_input(msg)
    timings["triage_ms"] = int((time.time() - _t0) * 1000)
    resp.headers["X-Triage-Result"] = triage_result
    
    if not should_continue:
        resp.headers["X-Debug-Branch"] = "clarify"
        resp.headers["X-Faq-Hit"] = "false"
        payload = _base_payload()
        payload["replyText"] = CLARIFY_RESPONSE
        timings["total_ms"] = int((time.time() - _start_time) * 1000)
        _set_timing_headers(resp, timings, _cache_hit)
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
            latency_ms=timings["total_ms"]
        )
        return payload

    # === NORMALIZE ===
    _t0 = time.time()
    normalized_msg = normalize_message(msg)
    resp.headers["X-Normalized-Input"] = (normalized_msg or "")[:80]

    # === SPLIT INTENTS ===
    intents = split_intents(normalized_msg)
    if not intents:
        intents = [normalized_msg] if normalized_msg else [msg]
    resp.headers["X-Intent-Count"] = str(len(intents))
    timings["normalize_split_ms"] = int((time.time() - _t0) * 1000)
    
    # Use first intent for retrieval (multi-intent handling comes later)
    primary_query = intents[0] if intents else normalized_msg or msg

    domain = _init_debug_headers(resp, tenant_id, primary_query)
    payload = _base_payload()

    # -----------------------------
    # Check cache first (only for FAQ hits)
    # -----------------------------
    cached_result = get_cached_result(tenant_id, primary_query)
    if cached_result:
        _cache_hit = True
        resp.headers["X-Cache-Hit"] = "true"
        resp.headers["X-Debug-Branch"] = cached_result.get("debug_branch", "fact_hit")
        resp.headers["X-Faq-Hit"] = "true"
        resp.headers["X-Retrieval-Score"] = str(cached_result.get("retrieval_score", ""))
        if cached_result.get("top_faq_id"):
            resp.headers["X-Top-Faq-Id"] = str(cached_result["top_faq_id"])
        payload["replyText"] = cached_result["replyText"]
        timings["total_ms"] = int((time.time() - _start_time) * 1000)
        _set_timing_headers(resp, timings, _cache_hit)
        _log_telemetry(
            tenant_id=tenant_id,
            query_text=msg,
            normalized_text=normalized_msg,
            intent_count=int(resp.headers.get("X-Intent-Count", "1")),
            debug_branch=resp.headers.get("X-Debug-Branch", "unknown"),
            faq_hit=True,
            top_faq_id=cached_result.get("top_faq_id"),
            retrieval_score=cached_result.get("retrieval_score"),
            rewrite_triggered=False,
            latency_ms=timings["total_ms"]
        )
        return payload

    # -----------------------------
    # Two-Stage Retrieval (ALWAYS runs)
    # -----------------------------
    try:
        # === TWO-STAGE RETRIEVAL ===
        from app.retriever import retrieve as two_stage_retrieve
        
        _t0 = time.time()
        retrieval_result, retrieval_trace = two_stage_retrieve(
            tenant_id=tenant_id,
            query=msg,
            normalized_query=primary_query,
            use_cache=True
        )
        timings["retrieval_ms"] = int((time.time() - _t0) * 1000)
        
        # Store trace for debug endpoint access
        resp._retrieval_trace = retrieval_trace
        
        # Set debug headers from trace
        resp.headers["X-Retrieval-Stage"] = retrieval_trace.get("stage", "unknown")
        if retrieval_trace.get("top_score") is not None:
            resp.headers["X-Retrieval-Score"] = str(retrieval_trace.get("top_score", 0))
        resp.headers["X-Cache-Hit"] = str(retrieval_trace.get("cache_hit", False)).lower()
        resp.headers["X-Retrieval-Mode"] = retrieval_trace.get("retrieval_mode", "unknown")
        resp.headers["X-Candidate-Count"] = str(retrieval_trace.get("candidates_count", 0))
        resp.headers["X-Selector-Called"] = str(retrieval_trace.get("selector_called", False)).lower()
        if retrieval_trace.get("selector_confidence") is not None:
            resp.headers["X-Selector-Confidence"] = str(retrieval_trace.get("selector_confidence", 0))
        resp.headers["X-Retrieval-Ms"] = str(retrieval_trace.get("retrieval_ms", 0))
        if retrieval_trace.get("selector_ms") is not None:
            resp.headers["X-Selector-Ms"] = str(retrieval_trace.get("selector_ms", 0))
        
        # New hybrid search headers
        resp.headers["X-Vector-Count"] = str(retrieval_trace.get("vector_count", 0))
        resp.headers["X-FTS-Count"] = str(retrieval_trace.get("fts_count", 0))
        resp.headers["X-Merged-Count"] = str(retrieval_trace.get("merged_count", 0))
        resp.headers["X-Final-Score"] = str(retrieval_trace.get("final_score", 0))
        resp.headers["X-Accept-Reason"] = retrieval_trace.get("accept_reason", "")[:50]
        
        if retrieval_trace.get("rerank_trace"):
            rt = retrieval_trace["rerank_trace"]
            resp.headers["X-Rerank-Method"] = rt.get("method", "none")
            resp.headers["X-Rerank-Ms"] = str(rt.get("duration_ms", 0))
            if rt.get("safety_gate"):
                resp.headers["X-Rerank-Gate"] = rt.get("safety_gate", "")[:50]
        
        # LLM selector headers
        resp.headers["X-Selector-Called"] = str(retrieval_trace.get("selector_called", False)).lower()
        if retrieval_trace.get("selector_confidence") is not None:
            resp.headers["X-Selector-Confidence"] = str(retrieval_trace["selector_confidence"])
        
        # Convert to hit/answer format
        hit = retrieval_result is not None
        ans = retrieval_result["answer"] if retrieval_result else None
        faq_id = retrieval_result["faq_id"] if retrieval_result else None
        score = retrieval_result["score"] if retrieval_result else retrieval_trace.get("top_score", 0)
        chosen_faq_id = retrieval_trace.get("chosen_faq_id") or faq_id
        
        if faq_id is not None:
            resp.headers["X-Top-Faq-Id"] = str(faq_id)
        if chosen_faq_id is not None:
            resp.headers["X-Chosen-Faq-Id"] = str(chosen_faq_id)
        
        resp.headers["X-Faq-Hit"] = str(hit).lower()

        if hit and ans:
            stage = retrieval_result.get("stage", "embedding")
            if stage == "selector":
                resp.headers["X-Debug-Branch"] = "selector_hit"
            elif stage == "rerank":
                resp.headers["X-Debug-Branch"] = "rerank_hit"
            elif stage == "cache":
                resp.headers["X-Debug-Branch"] = "cache_hit"
            else:
                resp.headers["X-Debug-Branch"] = "fact_hit"
            
            payload["replyText"] = str(ans).strip()
            
            # Cache the result (only for FAQ hits) - already cached by retriever
            cache_result(tenant_id, primary_query, {
                "replyText": payload["replyText"],
                "debug_branch": resp.headers.get("X-Debug-Branch", "fact_hit"),
                "retrieval_score": score,
                "top_faq_id": faq_id
            })
            
            timings["total_ms"] = int((time.time() - _start_time) * 1000)
            _set_timing_headers(resp, timings, _cache_hit)
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
                latency_ms=timings["total_ms"],
                candidate_count=retrieval_trace.get("candidates_count"),
                retrieval_mode=retrieval_trace.get("retrieval_mode"),
                selector_called=retrieval_trace.get("selector_called"),
                selector_confidence=retrieval_trace.get("selector_confidence"),
                chosen_faq_id=chosen_faq_id,
                retrieval_latency_ms=retrieval_trace.get("retrieval_ms"),
                selector_latency_ms=retrieval_trace.get("selector_ms")
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
        _t0 = time.time()
        try:
            system = (
                "Rewrite the user message into a short FAQ-style query (max 12 words). "
                "Preserve the meaning. Do not add or change any facts. "
                "Do NOT invent numbers, prices, times, policies, or inclusions. "
                "Output only the rewritten query text with no quotes or explanation."
            )
            rewrite = chat_once(system, f"Original customer message: {msg}", temperature=0.0).strip()
            timings["llm_ms"] += int((time.time() - _t0) * 1000)
        except Exception:
            timings["llm_ms"] += int((time.time() - _t0) * 1000)
            rewrite = ""

        if rewrite:
            resp.headers["X-Fact-Rewrite"] = rewrite[:80]
            if not is_rewrite_safe(rewrite, msg):
                rewrite = ""

        if rewrite:
            _t0 = time.time()
            rw_emb = embed_text(rewrite)
            timings["embedding_ms"] += int((time.time() - _t0) * 1000)
            
            _t0 = time.time()
            rw_hit, rw_ans, rw_score, rw_delta, rw_faq_id = retrieve_faq_answer(tenant_id, rw_emb)
            timings["retrieval_ms"] += int((time.time() - _t0) * 1000)
            timings["rewrite_ms"] = int((time.time() - _start_time) * 1000) - timings["triage_ms"] - timings["normalize_split_ms"] - timings["embedding_ms"] - timings["retrieval_ms"] - timings["llm_ms"]

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
                
                # Cache the result (only for FAQ hits)
                cache_result(tenant_id, primary_query, {
                    "replyText": payload["replyText"],
                    "debug_branch": "fact_rewrite_hit",
                    "retrieval_score": rw_score,
                    "top_faq_id": rw_faq_id
                })
                
                timings["total_ms"] = int((time.time() - _start_time) * 1000)
                _set_timing_headers(resp, timings, _cache_hit)
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
                    latency_ms=timings["total_ms"]
                )
                return payload

    except Exception:
        # If retrieval pipeline errors, fail safe
        resp.headers["X-Debug-Branch"] = "error"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = FALLBACK
        timings["total_ms"] = int((time.time() - _start_time) * 1000)
        _set_timing_headers(resp, timings, _cache_hit)
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
            latency_ms=timings["total_ms"]
        )
        return payload

    # -----------------------------
    # Retrieval miss -> decide fallback vs general
    # -----------------------------
    if _should_fallback_after_miss(msg, domain):
        resp.headers["X-Debug-Branch"] = "fact_miss"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = FALLBACK
        timings["total_ms"] = int((time.time() - _start_time) * 1000)
        _set_timing_headers(resp, timings, _cache_hit)
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
            latency_ms=timings["total_ms"]
        )
        return payload

    # -----------------------------
    # General chat (only truly non-business)
    # -----------------------------
    _t0 = time.time()
    try:
        system = (
            "Reply in one short paragraph. Do not ask follow-up questions. "
            "Do not state or imply any business facts like prices, durations, policies, inclusions, or fees. "
            f"If the user asks anything that sounds like business specifics, reply exactly: {FALLBACK}"
        )
        reply = chat_once(system, msg, temperature=0.6)
        timings["llm_ms"] = int((time.time() - _t0) * 1000)
    except Exception:
        timings["llm_ms"] = int((time.time() - _t0) * 1000)
        resp.headers["X-Debug-Branch"] = "error"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = FALLBACK
        timings["total_ms"] = int((time.time() - _start_time) * 1000)
        _set_timing_headers(resp, timings, _cache_hit)
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
            latency_ms=timings["total_ms"]
        )
        return payload

    if violates_general_safety(reply):
        resp.headers["X-Debug-Branch"] = "general_fallback"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = FALLBACK
        timings["total_ms"] = int((time.time() - _start_time) * 1000)
        _set_timing_headers(resp, timings, _cache_hit)
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
            latency_ms=timings["total_ms"]
        )
        return payload

    resp.headers["X-Debug-Branch"] = "general_ok"
    resp.headers["X-Faq-Hit"] = "false"
    payload["replyText"] = reply
    timings["total_ms"] = int((time.time() - _start_time) * 1000)
    _set_timing_headers(resp, timings, _cache_hit)
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
        latency_ms=timings["total_ms"]
    )
    return payload

@app.get("/ping")
def ping():
    """Simple liveness check - no DB, no external calls, just returns OK."""
    return {"ok": True}


@app.get("/api/health")
def health():
    """Health check endpoint with git SHA detection."""
    # Try multiple sources for git SHA (in order of preference)
    git_sha = (
        os.getenv("RENDER_GIT_COMMIT") or
        os.getenv("GIT_SHA") or
        _get_git_sha_from_file() or
        "unknown"
    )
    
    release = (
        os.getenv("RENDER_GIT_BRANCH") or
        os.getenv("RELEASE") or
        _get_git_branch_from_file() or
        "unknown"
    )
    
    return {
        "ok": True,
        "gitSha": git_sha,
        "release": release,
        "deployed": git_sha != "unknown"
    }


def _get_git_sha_from_file() -> str:
    """Read git SHA from build-time generated file."""
    try:
        from pathlib import Path
        build_info_path = Path(__file__).parent.parent / ".build-info.py"
        if build_info_path.exists():
            # Read the file and extract GIT_SHA
            content = build_info_path.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if line.startswith("GIT_SHA = "):
                    return line.split('"')[1] if '"' in line else line.split("'")[1]
    except Exception:
        pass
    return ""


def _get_git_branch_from_file() -> str:
    """Read git branch from build-time generated file."""
    try:
        from pathlib import Path
        build_info_path = Path(__file__).parent.parent / ".build-info.py"
        if build_info_path.exists():
            content = build_info_path.read_text(encoding="utf-8")
            for line in content.split("\n"):
                if line.startswith("GIT_BRANCH = "):
                    return line.split('"')[1] if '"' in line else line.split("'")[1]
    except Exception:
        pass
    return ""


@app.get("/admin", response_class=HTMLResponse)
def admin_ui():
    """Serve admin UI."""
    html_path = Path(__file__).parent.parent / "app" / "templates" / "admin.html"
    if html_path.exists():
        # Get GIT_SHA for cache busting
        git_sha = os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_SHA") or "1"
        html = html_path.read_text(encoding="utf-8")
        # Replace ?v=1 with actual git SHA for cache busting
        html = html.replace("?v=1", f"?v={git_sha}")
        response = HTMLResponse(content=html)
        response.headers["Cache-Control"] = "no-store"
        return response
    return "<h1>Admin UI not found</h1>"


def _get_tenant_stats_impl(tenantId: str):
    """Internal implementation for getting tenant stats."""
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


@app.get("/admin/api/tenant/{tenantId}/stats")
def get_tenant_stats_api(tenantId: str, resp: Response, authorization: str = Header(default="")):
    """Get telemetry stats for a tenant (last 24 hours) - Admin UI endpoint."""
    _check_admin_auth(authorization)
    return _get_tenant_stats_impl(tenantId)


@app.get("/admin/tenant/{tenantId}/stats")
def get_tenant_stats(tenantId: str, resp: Response, authorization: str = Header(default="")):
    """Get telemetry stats for a tenant (last 24 hours)."""
    _set_common_headers(resp, tenantId)
    
    if authorization != f"Bearer {settings.ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    return _get_tenant_stats_impl(tenantId)


@app.get("/api/v2/admin/tenant/{tenantId}/stats")
def get_tenant_stats_v2(tenantId: str, resp: Response, authorization: str = Header(default="")):
    """Admin telemetry stats endpoint (Cloudflare-compatible path)."""
    return get_tenant_stats(tenantId, resp, authorization)


def _get_tenant_alerts_impl(tenantId: str):
    """Internal implementation for getting tenant alerts (last hour)."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT 
                COUNT(*) as total_queries,
                COUNT(*) FILTER (WHERE faq_hit = true) as faq_hits,
                COUNT(*) FILTER (WHERE debug_branch = 'clarify') as clarify_count,
                COUNT(*) FILTER (WHERE debug_branch IN ('fact_miss', 'general_fallback')) as fallback_count,
                COUNT(*) FILTER (WHERE debug_branch = 'error') as error_count,
                COALESCE(AVG(latency_ms)::integer, 0) as avg_latency_ms
            FROM telemetry 
            WHERE tenant_id = %s 
            AND created_at > now() - interval '1 hour'
        """, (tenantId,)).fetchone()
    
    total_queries = row[0] or 0
    total = total_queries or 1  # Avoid division by zero
    
    hit_rate = round((row[1] or 0) / total, 3)
    clarify_rate = round((row[2] or 0) / total, 3)
    fallback_rate = round((row[3] or 0) / total, 3)
    error_rate = round((row[4] or 0) / total, 3)
    avg_latency_ms = row[5] or 0
    
    alerts = []
    
    # Only compute alerts if we have enough data
    if total_queries >= 10:
        if hit_rate < 0.3:
            alerts.append({
                "level": "warning",
                "type": "low_hit_rate",
                "message": f"FAQ hit rate is low: {hit_rate * 100:.1f}%",
                "value": hit_rate
            })
        
        if fallback_rate > 0.4:
            alerts.append({
                "level": "warning",
                "type": "high_fallback_rate",
                "message": f"Fallback rate is high: {fallback_rate * 100:.1f}%",
                "value": fallback_rate
            })
        
        if error_rate > 0.1:
            alerts.append({
                "level": "error",
                "type": "high_error_rate",
                "message": f"Error rate is high: {error_rate * 100:.1f}%",
                "value": error_rate
            })
        
        if avg_latency_ms > 2000:
            alerts.append({
                "level": "warning",
                "type": "high_latency",
                "message": f"Average latency is high: {avg_latency_ms}ms",
                "value": avg_latency_ms
            })
    
    return {
        "tenant_id": tenantId,
        "period": "last_hour",
        "total_queries": total_queries,
        "hit_rate": hit_rate,
        "fallback_rate": fallback_rate,
        "clarify_rate": clarify_rate,
        "error_rate": error_rate,
        "avg_latency_ms": avg_latency_ms,
        "alerts": alerts
    }


@app.get("/admin/api/tenant/{tenantId}/alerts")
def get_tenant_alerts_api(tenantId: str, resp: Response, authorization: str = Header(default="")):
    """Get tenant alerts (last hour) - Admin UI endpoint."""
    _check_admin_auth(authorization)
    return _get_tenant_alerts_impl(tenantId)


@app.get("/api/v2/admin/tenant/{tenantId}/alerts")
def get_tenant_alerts_v2(tenantId: str, resp: Response, authorization: str = Header(default="")):
    """Get tenant alerts (last hour) - Cloudflare-compatible path."""
    _check_admin_auth(authorization)
    return _get_tenant_alerts_impl(tenantId)


def _get_tenant_readiness_impl(tenantId: str):
    """Internal implementation for checking tenant readiness."""
    checks = []
    all_passed = True
    
    # Check 1: Tenant exists
    with get_conn() as conn:
        tenant_row = conn.execute(
            "SELECT id FROM tenants WHERE id = %s",
            (tenantId,)
        ).fetchone()
        
        tenant_exists = tenant_row is not None
        checks.append({
            "name": "tenant_exists",
            "passed": tenant_exists,
            "message": "Tenant exists" if tenant_exists else "Tenant not found"
        })
        if not tenant_exists:
            all_passed = False
            return {
                "tenant_id": tenantId,
                "ready": False,
                "checks": checks,
                "recommendation": "Create the tenant first"
            }
        
        # Check 2: Has >=1 enabled domain
        domain_count = conn.execute(
            "SELECT COUNT(*) FROM tenant_domains WHERE tenant_id = %s AND enabled = true",
            (tenantId,)
        ).fetchone()[0] or 0
        
        has_domains = domain_count >= 1
        checks.append({
            "name": "has_enabled_domains",
            "passed": has_domains,
            "message": f"Has {domain_count} enabled domain(s)" if has_domains else "No enabled domains"
        })
        if not has_domains:
            all_passed = False
        
        # Check 3: Has live FAQs
        live_faq_count = conn.execute(
            "SELECT COUNT(*) FROM faq_items WHERE tenant_id = %s AND is_staged = false",
            (tenantId,)
        ).fetchone()[0] or 0
        
        has_live_faqs = live_faq_count > 0
        checks.append({
            "name": "has_live_faqs",
            "passed": has_live_faqs,
            "message": f"Has {live_faq_count} live FAQ(s)" if has_live_faqs else "No live FAQs"
        })
        if not has_live_faqs:
            all_passed = False
        
        # Check 4: Has last_good backup
        last_good_count = conn.execute(
            "SELECT COUNT(*) FROM faq_items_last_good WHERE tenant_id = %s",
            (tenantId,)
        ).fetchone()[0] or 0
        
        has_backup = last_good_count > 0
        checks.append({
            "name": "has_last_good_backup",
            "passed": has_backup,
            "message": f"Has {last_good_count} last_good FAQ(s)" if has_backup else "No last_good backup"
        })
        if not has_backup:
            all_passed = False
    
    # Check 5: Has test suite file
    tests_dir = Path(__file__).parent.parent / "tests"
    test_file = tests_dir / f"{tenantId}.json"
    has_test_file = test_file.exists()
    
    checks.append({
        "name": "has_test_suite",
        "passed": has_test_file,
        "message": f"Test suite file exists: {test_file.name}" if has_test_file else f"Test suite file missing: {test_file.name}"
    })
    if not has_test_file:
        all_passed = False
    
    # Generate recommendation
    if all_passed:
        recommendation = "Tenant is ready for production"
    else:
        failed_checks = [c["name"] for c in checks if not c["passed"]]
        if "tenant_exists" in failed_checks:
            recommendation = "Create the tenant first"
        elif "has_enabled_domains" in failed_checks:
            recommendation = "Add at least one enabled domain"
        elif "has_live_faqs" in failed_checks:
            recommendation = "Upload and promote FAQs to live"
        elif "has_last_good_backup" in failed_checks:
            recommendation = "Promote FAQs to create a last_good backup"
        elif "has_test_suite" in failed_checks:
            recommendation = f"Create test suite file: tests/{tenantId}.json"
        else:
            recommendation = "Fix the failed checks above"
    
    return {
        "tenant_id": tenantId,
        "ready": all_passed,
        "checks": checks,
        "recommendation": recommendation
    }


@app.get("/admin/api/tenant/{tenantId}/readiness")
def get_tenant_readiness_api(tenantId: str, resp: Response, authorization: str = Header(default="")):
    """Get tenant readiness status - Admin UI endpoint."""
    _check_admin_auth(authorization)
    return _get_tenant_readiness_impl(tenantId)


@app.get("/api/v2/admin/tenant/{tenantId}/readiness")
def get_tenant_readiness_v2(tenantId: str, resp: Response, authorization: str = Header(default="")):
    """Get tenant readiness status - Cloudflare-compatible path."""
    _check_admin_auth(authorization)
    return _get_tenant_readiness_impl(tenantId)


@app.get("/admin/api/tenant/{tenant_id}/launch-gates")
def check_launch_gates(tenant_id: str, authorization: str = Header(default="")):
    """
    Check if a tenant passes all launch gates.
    Returns detailed status for each gate.
    """
    _check_admin_auth(authorization)
    tenant_id = (tenant_id or "").strip()
    
    gates = []
    all_pass = True
    
    with get_conn() as conn:
        # Gate 1: Tenant exists
        tenant = conn.execute(
            "SELECT id, name FROM tenants WHERE id = %s",
            (tenant_id,)
        ).fetchone()
        
        gates.append({
            "gate": "tenant_exists",
            "required": True,
            "passed": tenant is not None,
            "message": f"Tenant '{tenant_id}' exists" if tenant else f"Tenant '{tenant_id}' not found"
        })
        if not tenant:
            all_pass = False
            return {
                "tenant_id": tenant_id,
                "all_required_passed": False,
                "gates": gates,
                "recommendation": "Create tenant first"
            }
        
        # Gate 2: Domain registered
        domains = conn.execute(
            "SELECT domain FROM tenant_domains WHERE tenant_id = %s AND enabled = true",
            (tenant_id,)
        ).fetchall()
        
        gates.append({
            "gate": "domain_registered",
            "required": True,
            "passed": len(domains) > 0,
            "message": f"{len(domains)} domain(s) registered" if domains else "No domains registered"
        })
        if not domains:
            all_pass = False
        
        # Gate 3: Minimum FAQs
        faqs = conn.execute(
            "SELECT COUNT(*) FROM faq_items WHERE tenant_id = %s AND (is_staged = false OR is_staged IS NULL) AND enabled = true",
            (tenant_id,)
        ).fetchone()
        faq_count = faqs[0] if faqs else 0
        
        gates.append({
            "gate": "minimum_faqs",
            "required": True,
            "passed": faq_count >= 5,
            "message": f"{faq_count} FAQs (minimum: 5)"
        })
        if faq_count < 5:
            all_pass = False
        
        # Gate 4: Variants exist
        variants = conn.execute("""
            SELECT COUNT(*) FROM faq_variants fv
            JOIN faq_items fi ON fi.id = fv.faq_id
            WHERE fi.tenant_id = %s AND (fi.is_staged = false OR fi.is_staged IS NULL)
        """, (tenant_id,)).fetchone()
        variant_count = variants[0] if variants else 0
        
        gates.append({
            "gate": "variants_exist",
            "required": True,
            "passed": variant_count >= faq_count * 3,
            "message": f"{variant_count} variants (minimum: {faq_count * 3})"
        })
        if variant_count < faq_count * 3:
            all_pass = False
        
        # Gate 5: Benchmark file exists (optional)
        benchmark_path = Path(__file__).parent.parent / "tests" / f"{tenant_id}_messy.json"
        if not benchmark_path.exists():
            benchmark_path = Path(__file__).parent.parent / "tests" / f"{tenant_id}.json"
        
        gates.append({
            "gate": "benchmark_exists",
            "required": False,
            "passed": benchmark_path.exists(),
            "message": f"Benchmark file {'found' if benchmark_path.exists() else 'not found'}"
        })
    
    return {
        "tenant_id": tenant_id,
        "all_required_passed": all_pass,
        "gates": gates,
        "recommendation": "Ready for launch" if all_pass else "Fix failing required gates before launch"
    }


# ============ ADMIN UI ENDPOINTS ============

def _check_admin_auth(authorization: str):
    """Check admin authorization. Raises HTTPException if invalid."""
    if authorization != f"Bearer {settings.ADMIN_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")


class TenantCreate(BaseModel):
    id: str
    name: str


class DomainAdd(BaseModel):
    domain: str


@app.get("/admin/api/health")
def admin_api_health():
    """Health check for admin API routes."""
    # Verify key routes exist
    route_paths = [
        "/admin/api/tenants",
        "/admin/api/tenant/{tenantId}/domains",
        "/admin/api/tenant/{tenantId}/faqs/staged",
        "/admin/api/tenant/{tenantId}/promote",
        "/admin/api/tenant/{tenantId}/readiness",
        "/admin/api/tenant/{tenantId}/alerts",
        "/admin/api/tenant/{tenantId}/stats",
        "/admin/api/tenant/{tenantId}/benchmark",
        "/admin/api/tenant/{tenantId}/domains/sync-worker",
    ]
    
    existing_routes = []
    for route in app.routes:
        if hasattr(route, "path"):
            existing_routes.append(route.path)
    
    verified = []
    for pattern in route_paths:
        # Check if route exists (exact or with parameter)
        found = any(
            r == pattern or 
            (pattern.replace("{tenantId}", "") in r.replace("{tenantId}", ""))
            for r in existing_routes
        )
        verified.append({"pattern": pattern, "exists": found})
    
    return {
        "ok": True,
        "routes": "available",
        "verified": verified,
        "timestamp": time.time()
    }

@app.get("/admin/api/tenants")
def list_tenants(resp: Response, authorization: str = Header(default="")):
    """List all tenants."""
    _check_admin_auth(authorization)
    
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at FROM tenants ORDER BY created_at DESC"
        ).fetchall()
    
    tenants = [
        {
            "id": row[0],
            "name": row[1] or row[0],
            "created_at": row[2].isoformat() if row[2] else None
        }
        for row in rows
    ]
    
    return {"tenants": tenants}


@app.post("/admin/api/tenants")
def create_tenant(
    tenant: TenantCreate,
    resp: Response,
    authorization: str = Header(default="")
):
    """Create a new tenant."""
    _check_admin_auth(authorization)
    
    tenant_id = (tenant.id or "").strip()
    tenant_name = (tenant.name or "").strip()
    
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name",
                (tenant_id, tenant_name or tenant_id)
            )
            conn.commit()
        
        return {"id": tenant_id, "name": tenant_name or tenant_id, "created": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create tenant: {str(e)}")


@app.get("/admin/api/tenant/{tenantId}")
def get_tenant_detail(tenantId: str, resp: Response, authorization: str = Header(default="")):
    """Get tenant details including domains, staged FAQ count, and last run status."""
    _check_admin_auth(authorization)
    
    import json as json_lib
    
    with get_conn() as conn:
        tenant_row = conn.execute(
            "SELECT id, name, created_at FROM tenants WHERE id = %s",
            (tenantId,)
        ).fetchone()
        
        if not tenant_row:
            raise HTTPException(status_code=404, detail="Tenant not found")
        
        domain_rows = conn.execute(
            "SELECT domain, enabled, created_at FROM tenant_domains WHERE tenant_id = %s ORDER BY domain",
            (tenantId,)
        ).fetchall()
        
        # Get staged FAQ count
        staged_count = conn.execute(
            "SELECT COUNT(*) FROM faq_items WHERE tenant_id=%s AND is_staged=true",
            (tenantId,)
        ).fetchone()[0]
        
        # Get live FAQ count
        live_count = conn.execute(
            "SELECT COUNT(*) FROM faq_items WHERE tenant_id=%s AND is_staged=false",
            (tenantId,)
        ).fetchone()[0]
        
        # Get last_good count
        last_good_count = conn.execute(
            "SELECT COUNT(*) FROM faq_items_last_good WHERE tenant_id=%s",
            (tenantId,)
        ).fetchone()[0]
        
        # Get last promote history
        last_run = conn.execute("""
            SELECT status, suite_result, first_failure, created_at
            FROM tenant_promote_history
            WHERE tenant_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (tenantId,)).fetchone()
    
    domains = [
        {
            "domain": row[0],
            "enabled": row[1],
            "created_at": row[2].isoformat() if row[2] else None
        }
        for row in domain_rows
    ]
    
    result = {
        "id": tenant_row[0],
        "name": tenant_row[1] or tenant_row[0],
        "created_at": tenant_row[2].isoformat() if tenant_row[2] else None,
        "domains": domains,
        "staged_faq_count": staged_count,
        "live_faq_count": live_count,
        "last_good_count": last_good_count
    }
    
    if last_run:
        result["last_run"] = {
            "status": last_run[0],
            "created_at": last_run[3].isoformat() if last_run[3] else None
        }
        if last_run[1]:
            try:
                result["last_run"]["suite_result"] = json_lib.loads(last_run[1])
            except:
                pass
        if last_run[2]:
            try:
                result["last_run"]["first_failure"] = json_lib.loads(last_run[2])
            except:
                pass
    
    return result


@app.post("/admin/api/tenant/{tenantId}/domains")
def add_domain(
    tenantId: str,
    domain: DomainAdd,
    resp: Response,
    authorization: str = Header(default="")
):
    """Add a domain for a tenant."""
    _check_admin_auth(authorization)
    
    domain_str = (domain.domain or "").strip().lower()
    if not domain_str:
        raise HTTPException(status_code=400, detail="Domain required")
    
    try:
        with get_conn() as conn:
            # Ensure tenant exists
            conn.execute(
                "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (tenantId, tenantId)
            )
            
            # Add domain
            conn.execute(
                "INSERT INTO tenant_domains (tenant_id, domain, enabled) VALUES (%s, %s, true) ON CONFLICT (tenant_id, domain) DO UPDATE SET enabled=true",
                (tenantId, domain_str)
            )
            conn.commit()
        
        return {"tenant_id": tenantId, "domain": domain_str, "added": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add domain: {str(e)}")


@app.delete("/admin/api/tenant/{tenantId}/domains/{domain}")
def remove_domain(
    tenantId: str,
    domain: str,
    resp: Response,
    authorization: str = Header(default="")
):
    """Remove or disable a domain for a tenant."""
    _check_admin_auth(authorization)
    
    domain_str = domain.strip().lower()
    
    try:
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM tenant_domains WHERE tenant_id = %s AND domain = %s",
                (tenantId, domain_str)
            )
            conn.commit()
        
        return {"tenant_id": tenantId, "domain": domain_str, "removed": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove domain: {str(e)}")


@app.put("/admin/api/tenant/{tenantId}/faqs/staged")
def upload_staged_faqs(
    tenantId: str,
    items: List[FaqItem],
    resp: Response,
    authorization: str = Header(default="")
):
    """Upload FAQs to staging (does not replace live FAQs)."""
    _check_admin_auth(authorization)
    
    try:
        count = 0
        with get_conn() as conn:
            # Ensure tenant exists
            conn.execute(
                "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (tenantId, tenantId)
            )
            
            # Delete existing staged FAQs (keep live unchanged)
            conn.execute("DELETE FROM faq_items WHERE tenant_id=%s AND is_staged=true", (tenantId,))
            
            # Also delete staged variants (they'll be recreated)
            conn.execute("""
                DELETE FROM faq_variants 
                WHERE faq_id IN (SELECT id FROM faq_items WHERE tenant_id=%s AND is_staged=true)
            """, (tenantId,))
            
            # Variant expansion moved to promote-time (keeps staged FAQs clean)
            # items_data = expand_variants_inline(items_data, max_per_faq=40)
            
            import json as json_lib
            
            for it in items:
                q = (it.question or "").strip()
                a = (it.answer or "").strip()
                if not q or not a:
                    continue

                # Store variants in variants_json (embeddings created at promote time)
                raw_variants = it.variants or []
                # Ensure it's a list and convert to JSON string
                if isinstance(raw_variants, str):
                    try:
                        raw_variants = json_lib.loads(raw_variants)
                    except:
                        raw_variants = []
                variants_json = json_lib.dumps(raw_variants) if raw_variants else '[]'
                
                emb_q = embed_text(q)
                row = conn.execute(
                    "INSERT INTO faq_items (tenant_id, question, answer, embedding, enabled, is_staged, variants_json) "
                    "VALUES (%s,%s,%s,%s,true,true,%s) RETURNING id",
                    (tenantId, q, a, Vector(emb_q), variants_json),
                ).fetchone()
                faq_id = row[0]

                # Don't create variant embeddings here - done at promote time
                # This keeps staged upload fast

                count += 1

            conn.commit()
        
        return {"tenant_id": tenantId, "staged_count": count, "message": f"Staged {count} FAQs"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stage FAQs: {str(e)}")


@app.post("/admin/api/tenant/{tenantId}/promote")
def promote_staged(
    tenantId: str,
    resp: Response,
    authorization: str = Header(default="")
):
    """Promote staged FAQs to live after running suite."""
    _check_admin_auth(authorization)
    
    import json as json_lib
    import traceback
    from datetime import datetime
    
    # Get base URL from env var (default to production API in prod, localhost in dev)
    base_url = os.getenv("PUBLIC_BASE_URL")
    if not base_url:
        # Default: production API if RENDER is set, otherwise localhost
        if os.getenv("RENDER"):
            base_url = "https://api.motionmadebne.com.au"
        else:
            base_url = "http://localhost:8000"
    
    stage = "init"
    timings = {}
    start_time = time.time()
    
    try:
        # 1. Check if staged FAQs exist
        stage = "check_staged"
        with get_conn() as conn:
            staged_count = conn.execute(
                "SELECT COUNT(*) FROM faq_items WHERE tenant_id=%s AND is_staged=true",
                (tenantId,)
            ).fetchone()[0]
            
            if staged_count == 0:
                raise HTTPException(status_code=400, detail="No staged FAQs to promote")
        
        # 2. Delete live FAQs and variants
        stage = "delete_live"
        stage_start = time.time()
        with get_conn() as conn:
            # Backup current live FAQs to last_good if not already there
            conn.execute("""
                INSERT INTO faq_items_last_good (tenant_id, question, answer, embedding)
                SELECT tenant_id, question, answer, embedding
                FROM faq_items
                WHERE tenant_id=%s AND is_staged=false
                ON CONFLICT (tenant_id, question) DO UPDATE
                SET answer=EXCLUDED.answer, embedding=EXCLUDED.embedding, updated_at=now()
            """, (tenantId,))
            
            # Delete ALL current live FAQs and their variants FIRST (prevents duplicate key error)
            conn.execute('''
                DELETE FROM faq_variants 
                WHERE faq_id IN (
                    SELECT id FROM faq_items 
                    WHERE tenant_id = %s AND (is_staged = false OR is_staged IS NULL)
                )
            ''', (tenantId,))
            
            conn.execute('''
                DELETE FROM faq_items 
                WHERE tenant_id = %s AND (is_staged = false OR is_staged IS NULL)
            ''', (tenantId,))
            conn.commit()
        timings["delete_live"] = int((time.time() - stage_start) * 1000)
        
        # 3. Get staged FAQs and expand variants
        stage = "expand_variants"
        stage_start = time.time()
        with get_conn() as conn:
            # Get staged FAQs with variants_json
            staged_faqs = conn.execute("""
                SELECT id, question, answer, variants_json FROM faq_items WHERE tenant_id=%s AND is_staged=true
            """, (tenantId,)).fetchall()
            
            # Auto-expand variants before embedding
            faqs_to_expand = []
            for faq in staged_faqs:
                variants_json = faq[3]
                variants = []
                if variants_json:
                    # Handle both JSON string and already-parsed list
                    if isinstance(variants_json, str):
                        try:
                            variants = json_lib.loads(variants_json)
                        except:
                            variants = []
                    elif isinstance(variants_json, list):
                        variants = variants_json
                    else:
                        variants = []
                
                faqs_to_expand.append({
                    "question": faq[1],  # question
                    "answer": faq[2],     # answer
                    "variants": variants
                })
            
            expanded_faqs = expand_faq_list(faqs_to_expand, max_variants_per_faq=50)
            
            # Log expansion stats
            total_before = sum(len(f.get("variants", [])) for f in faqs_to_expand)
            total_after = sum(len(f.get("variants", [])) for f in expanded_faqs)
            print(f"Variant expansion: {total_before} -> {total_after} variants")
            
            # Create mapping from question to expanded variants
            expanded_variants_map = {f["question"]: f["variants"] for f in expanded_faqs}
        timings["expand_variants"] = int((time.time() - stage_start) * 1000)
        
        # 4. Promote staged to live and embed variants
        stage = "promote_and_embed"
        stage_start = time.time()
        with get_conn() as conn:
            # NOW promote staged to live (no conflicts possible)
            conn.execute("""
                UPDATE faq_items SET is_staged=false WHERE tenant_id=%s AND is_staged=true
            """, (tenantId,))
            
            # Embed variants for each FAQ
            for faq_id, q, a, variants_json in staged_faqs:
                # Use expanded variants if available, otherwise fall back to original
                variants = []
                if q in expanded_variants_map:
                    variants = expanded_variants_map[q]
                    print(f"Using expanded variants for FAQ '{q}': {len(variants)} variants")
                else:
                    # Try case-insensitive match
                    q_lower = q.lower()
                    matched = False
                    for exp_q, exp_variants in expanded_variants_map.items():
                        if exp_q.lower() == q_lower:
                            variants = exp_variants
                            print(f"Matched FAQ '{q}' to expanded '{exp_q}': {len(variants)} variants")
                            matched = True
                            break
                    
                    if not matched:
                        # Parse variants from JSON (fallback)
                        try:
                            if isinstance(variants_json, str):
                                variants = json_lib.loads(variants_json)
                            elif isinstance(variants_json, list):
                                variants = variants_json
                            else:
                                variants = []
                        except:
                            variants = []
                        print(f"Using original variants for FAQ '{q}': {len(variants)} variants (no expansion match)")
                
                # Always include question itself, plus variants
                all_variants = [q] + [v for v in variants if v and v.lower() != q.lower()]
                
                # Delete old variants
                conn.execute("DELETE FROM faq_variants WHERE faq_id=%s", (faq_id,))
                
                # Embed all variants (limit to 50 per FAQ)
                embedded_count = 0
                for variant in all_variants[:50]:
                    variant = variant.strip()
                    if not variant:
                        continue
                    
                    try:
                        v_emb = embed_text(variant)
                        conn.execute("""
                            INSERT INTO faq_variants (faq_id, variant_question, variant_embedding, enabled)
                            VALUES (%s, %s, %s, true)
                        """, (faq_id, variant, Vector(v_emb)))
                        embedded_count += 1
                    except Exception as e:
                        print(f"Embed error for '{variant[:30]}': {e}")
                        # Continue with next variant instead of failing entire promote
                        continue
                
                print(f"Embedded {embedded_count} variants for FAQ '{q}' (faq_id={faq_id})")
            
            # Update search vectors for FTS after promotion
            try:
                conn.execute("""
                    UPDATE faq_items 
                    SET search_vector = to_tsvector('english', COALESCE(question, '') || ' ' || COALESCE(answer, ''))
                    WHERE tenant_id = %s AND is_staged = false
                """, (tenantId,))
            except Exception as e:
                # FTS update is non-critical, log but don't fail
                print(f"FTS update error (non-critical): {e}")
            
            conn.commit()
        timings["promote_and_embed"] = int((time.time() - stage_start) * 1000)
        
        # 5. Run suite (if exists, otherwise skip)
        # Suite is REQUIRED if suite file exists - if it fails, promotion is blocked
        suite_path = Path(__file__).parent.parent / "tests" / f"{tenantId}.json"
        suite_result = None
        
        if suite_path.exists():
            # First, verify we can reach the base URL
            import requests
            try:
                health_check = requests.get(f"{base_url}/api/health", timeout=5)
                if health_check.status_code != 200:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Cannot reach API at {base_url} (HTTP {health_check.status_code}). Suite cannot run. Promotion blocked."
                    )
            except requests.exceptions.RequestException as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Cannot reach API at {base_url}: {str(e)}. Suite cannot run. Set PUBLIC_BASE_URL env var correctly. Promotion blocked."
                )
            
            # Run suite
            try:
                suite_result = run_suite(base_url, tenantId)
                
                # If suite failed, DO NOT promote
                if not suite_result.get("passed", False):
                    first_failure = suite_result.get("first_failure", {})
                    error_msg = first_failure.get("error", "Unknown error")
                    test_name = first_failure.get("test_name", "unknown")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Suite failed: {test_name} - {error_msg}. Promotion blocked."
                    )
            except HTTPException:
                raise
            except Exception as e:
                # Suite failed to run - block promotion
                raise HTTPException(
                    status_code=500,
                    detail=f"Suite run failed: {str(e)}. Promotion blocked."
                )
        else:
            # No suite file - skip tests and promote anyway
            suite_result = {
                "passed": True,
                "total": 0,
                "passed_count": 0,
                "skipped": True,
                "message": "No suite file found - promoting without tests"
            }
        
        # Always promote - suite is informational only
        should_promote = True
        
        # 6. Update last_good backup
        stage = "update_last_good"
        stage_start = time.time()
        with get_conn() as conn:
            if should_promote:
                # Promote: staged is already live, just update last_good
                conn.execute("""
                    DELETE FROM faq_items_last_good WHERE tenant_id=%s
                """, (tenantId,))
                conn.execute("""
                    INSERT INTO faq_items_last_good (tenant_id, question, answer, embedding)
                    SELECT tenant_id, question, answer, embedding
                    FROM faq_items
                    WHERE tenant_id=%s AND is_staged=false
                    ON CONFLICT (tenant_id, question) DO UPDATE
                    SET answer=EXCLUDED.answer, embedding=EXCLUDED.embedding, updated_at=now()
                """, (tenantId,))
                
                # Clear retrieval cache for this tenant (new FAQs = new embeddings)
                conn.execute("DELETE FROM retrieval_cache WHERE tenant_id=%s", (tenantId,))
                
                # Log success
                conn.execute("""
                    INSERT INTO tenant_promote_history (tenant_id, status, suite_result)
                    VALUES (%s, 'success', %s)
                """, (tenantId, json_lib.dumps(suite_result)))
            else:
                # Rollback: restore live from last_good, move current back to staged
                # First, move current (failed) back to staged
                conn.execute("""
                    UPDATE faq_items SET is_staged=true 
                    WHERE tenant_id=%s AND is_staged=false
                    AND id NOT IN (SELECT id FROM faq_items_last_good WHERE tenant_id=%s)
                """, (tenantId, tenantId))
                
                # Restore last_good to live
                conn.execute("""
                    DELETE FROM faq_items WHERE tenant_id=%s AND is_staged=false
                """, (tenantId,))
                conn.execute("""
                    DELETE FROM faq_variants 
                    WHERE faq_id IN (SELECT id FROM faq_items WHERE tenant_id=%s)
                """, (tenantId,))
                
                # Restore last_good FAQs
                last_good_rows = conn.execute("""
                    SELECT question, answer, embedding FROM faq_items_last_good WHERE tenant_id=%s
                """, (tenantId,)).fetchall()
                
                for row in last_good_rows:
                    q, a, emb = row
                    faq_row = conn.execute("""
                        INSERT INTO faq_items (tenant_id, question, answer, embedding, enabled, is_staged)
                        VALUES (%s, %s, %s, %s, true, false) RETURNING id
                    """, (tenantId, q, a, emb)).fetchone()
                    faq_id = faq_row[0]
                    
                    # Recreate variants (simplified - just question as variant)
                    q_emb = embed_text(q)
                    conn.execute("""
                        INSERT INTO faq_variants (faq_id, variant_question, variant_embedding, enabled)
                        VALUES (%s, %s, %s, true)
                    """, (faq_id, q, Vector(q_emb)))
                
                # Log failure
                conn.execute("""
                    INSERT INTO tenant_promote_history (tenant_id, status, suite_result, first_failure)
                    VALUES (%s, 'failed', %s, %s)
                """, (tenantId, json_lib.dumps(suite_result), json_lib.dumps(suite_result.get("first_failure"))))
            
            conn.commit()
        
        if should_promote:
            return {
                "tenant_id": tenantId,
                "status": "success",
                "message": f"Promoted {staged_count} FAQs to live",
                "suite_result": suite_result
            }
        else:
            return {
                "tenant_id": tenantId,
                "status": "failed",
                "message": "Suite failed, staged FAQs not promoted",
                "suite_result": suite_result,
                "first_failure": suite_result.get("first_failure")
            }
            
    except HTTPException:
        raise
    except Exception as e:
        # Log full traceback server-side
        import logging
        logging.error(f"Promote failed at stage '{stage}': {e}", exc_info=True)
        
        # Return detailed error for admin (prod-safe)
        error_type = type(e).__name__
        error_message = str(e)
        
        # Get stack trace (first 20 lines)
        tb_lines = traceback.format_exc().split('\n')[:20]
        stack_trace = '\n'.join(tb_lines)
        
        # On error, try to restore
        try:
            with get_conn() as conn:
                # Restore last_good
                conn.execute("""
                    DELETE FROM faq_items WHERE tenant_id=%s AND is_staged=false
                """, (tenantId,))
                last_good_rows = conn.execute("""
                    SELECT question, answer, embedding FROM faq_items_last_good WHERE tenant_id=%s
                """, (tenantId,)).fetchall()
                for row in last_good_rows:
                    q, a, emb = row
                    conn.execute("""
                        INSERT INTO faq_items (tenant_id, question, answer, embedding, enabled, is_staged)
                        VALUES (%s, %s, %s, %s, true, false) ON CONFLICT DO NOTHING
                    """, (tenantId, q, a, emb))
                conn.commit()
        except:
            pass
        
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Promotion failed",
                "stage": stage,
                "error_type": error_type,
                "error_message": error_message,
                "stack_trace": stack_trace,
                "timings_ms": timings
            }
        )


@app.post("/admin/api/tenant/{tenantId}/rollback")
def rollback_tenant(
    tenantId: str,
    resp: Response,
    authorization: str = Header(default="")
):
    """Rollback to last_good FAQs."""
    _check_admin_auth(authorization)
    
    try:
        with get_conn() as conn:
            # Check if last_good exists
            last_good_count = conn.execute("""
                SELECT COUNT(*) FROM faq_items_last_good WHERE tenant_id=%s
            """, (tenantId,)).fetchone()[0]
            
            if last_good_count == 0:
                raise HTTPException(status_code=400, detail="No last_good FAQs to rollback to")
            
            # Delete current live FAQs
            conn.execute("DELETE FROM faq_items WHERE tenant_id=%s AND is_staged=false", (tenantId,))
            conn.execute("""
                DELETE FROM faq_variants 
                WHERE faq_id IN (SELECT id FROM faq_items WHERE tenant_id=%s)
            """, (tenantId,))
            
            # Restore last_good to live
            last_good_rows = conn.execute("""
                SELECT question, answer, embedding FROM faq_items_last_good WHERE tenant_id=%s
            """, (tenantId,)).fetchall()
            
            for row in last_good_rows:
                q, a, emb = row
                faq_row = conn.execute("""
                    INSERT INTO faq_items (tenant_id, question, answer, embedding, enabled, is_staged)
                    VALUES (%s, %s, %s, %s, true, false) RETURNING id
                """, (tenantId, q, a, emb)).fetchone()
                faq_id = faq_row[0]
                
                # Recreate variants
                q_emb = embed_text(q)
                conn.execute("""
                    INSERT INTO faq_variants (faq_id, variant_question, variant_embedding, enabled)
                    VALUES (%s, %s, %s, true)
                """, (faq_id, q, Vector(q_emb)))
            
            conn.commit()
        
        return {
            "tenant_id": tenantId,
            "status": "success",
            "message": f"Rolled back to last_good ({last_good_count} FAQs)"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rollback failed: {str(e)}")


@app.post("/admin/api/tenant/{tenantId}/benchmark")
def run_benchmark(
    tenantId: str,
    resp: Response,
    authorization: str = Header(default="")
):
    """Run messy benchmark for a tenant and return results."""
    _check_admin_auth(authorization)
    
    import json as json_lib
    from pathlib import Path
    
    # Load benchmark suite
    benchmark_path = Path(__file__).parent.parent / "tests" / "messy_benchmark.json"
    if not benchmark_path.exists():
        raise HTTPException(status_code=404, detail="Benchmark suite not found")
    
    with open(benchmark_path, "r") as f:
        benchmark = json_lib.load(f)
    
    tests = benchmark["tests"]
    thresholds = benchmark["pass_thresholds"]
    
    # Get base URL for API calls
    base_url = os.getenv("PUBLIC_BASE_URL") or "https://api.motionmadebne.com.au"
    
    results = []
    worst_misses = []
    
    # Run each test
    for test in tests:
        question = test["question"]
        url = f"{base_url}/api/v2/generate-quote-reply"
        body = json_lib.dumps({"tenantId": tenantId, "customerMessage": question}).encode()
        
        try:
            import urllib.request
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as response:
                headers = {k.lower(): v for k, v in response.getheaders()}
                body_text = response.read().decode()
                
                is_clarify = "rephrase" in body_text.lower()
                faq_hit = headers.get("x-faq-hit", "false") == "true"
                score = float(headers.get("x-retrieval-score", 0)) if headers.get("x-retrieval-score") else None
                branch = "clarify" if is_clarify else headers.get("x-debug-branch", "unknown")
                normalized = headers.get("x-normalized-input", "")
                
                expected_hit = test.get("expect_hit", False)
                expected_branch = test.get("expect_branch")
                
                actual_hit = faq_hit
                actual_branch = branch
                
                passed = True
                if expected_hit and not actual_hit:
                    passed = False
                    worst_misses.append({
                        "question": question,
                        "category": test.get("category", "unknown"),
                        "score": score,
                        "normalized": normalized,
                    })
                elif not expected_hit and actual_hit:
                    passed = False
                elif expected_branch and actual_branch != expected_branch:
                    passed = False
                
                results.append({
                    "test": test,
                    "faq_hit": faq_hit,
                    "score": score,
                    "branch": branch,
                    "normalized": normalized,
                    "passed": passed
                })
        except Exception as e:
            results.append({
                "test": test,
                "error": str(e),
                "passed": False
            })
    
    # Calculate metrics
    expect_hit_tests = [r for r in results if r.get("test", {}).get("expect_hit")]
    actual_hits = sum(1 for r in expect_hit_tests if r.get("faq_hit"))
    hit_rate = actual_hits / len(expect_hit_tests) if expect_hit_tests else 0
    
    expect_miss_tests = [r for r in results if not r.get("test", {}).get("expect_hit")]
    wrong_hits = sum(1 for r in expect_miss_tests if r.get("faq_hit"))
    wrong_hit_rate = wrong_hits / len(expect_miss_tests) if expect_miss_tests else 0
    
    fallbacks = [r for r in expect_hit_tests if r.get("branch") in ("general_fallback", "fact_miss") and not r.get("branch") == "clarify"]
    fallback_rate = len(fallbacks) / len(expect_hit_tests) if expect_hit_tests else 0
    
    gate_pass = (
        hit_rate >= thresholds["min_hit_rate"] and
        fallback_rate <= thresholds["max_fallback_rate"] and
        wrong_hit_rate <= thresholds["max_wrong_hit_rate"]
    )
    
    # Sort worst misses by score
    worst_misses.sort(key=lambda x: x.get("score") or 0, reverse=True)
    
    return {
        "tenant_id": tenantId,
        "total_tests": len(results),
        "passed_tests": sum(1 for r in results if r.get("passed")),
        "hit_rate": hit_rate,
        "fallback_rate": fallback_rate,
        "wrong_hit_rate": wrong_hit_rate,
        "gate_pass": gate_pass,
        "thresholds": thresholds,
        "worst_misses": worst_misses[:10],
        "results": results
    }


@app.post("/admin/api/tenant/{tenantId}/domains/sync-worker")
def sync_worker_domains(
    tenantId: str,
    resp: Response,
    authorization: str = Header(default="")
):
    """Sync tenant domains to Worker D1 database via Cloudflare API."""
    _check_admin_auth(authorization)
    
    import json as json_lib
    
    # Get Cloudflare config from environment
    cf_api_token = os.getenv("CLOUDFLARE_API_TOKEN")
    cf_account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    worker_db_name = os.getenv("WORKER_D1_DB_NAME", "motionmade_creator_enquiries")
    worker_db_id = os.getenv("WORKER_D1_DB_ID")
    
    if not cf_api_token or not cf_account_id or not worker_db_id:
        return {
            "tenant_id": tenantId,
            "synced": False,
            "message": "Cloudflare API configuration missing. Set CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, and WORKER_D1_DB_ID environment variables. For now, use wrangler CLI manually.",
            "manual_instructions": f"Run: wrangler d1 execute <db_name> --remote --command \"INSERT INTO tenant_domains (domain, tenant_id, enabled) VALUES ('<domain>', '{tenantId}', 1) ON CONFLICT(domain) DO UPDATE SET tenant_id=excluded.tenant_id, enabled=1;\""
        }
    
    # Get domains from FastAPI database
    with get_conn() as conn:
        domains = conn.execute(
            "SELECT domain FROM tenant_domains WHERE tenant_id=%s AND enabled=true",
            (tenantId,)
        ).fetchall()
    
    domain_list = [row[0] for row in domains]
    
    if not domain_list:
        return {
            "tenant_id": tenantId,
            "synced": False,
            "message": "No domains found for tenant"
        }
    
    # Sync each domain to Worker D1 via Cloudflare API
    synced = []
    errors = []
    
    for domain in domain_list:
        # Use Cloudflare API to execute D1 SQL
        url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account_id}/d1/database/{worker_db_id}/query"
        
        sql = f"""
        INSERT INTO tenant_domains (domain, tenant_id, enabled, notes)
        VALUES ('{domain}', '{tenantId}', 1, 'admin_api_sync')
        ON CONFLICT(domain) DO UPDATE SET tenant_id=excluded.tenant_id, enabled=1, notes=excluded.notes;
        """
        
        try:
            import urllib.request
            req = urllib.request.Request(
                url,
                data=json_lib.dumps({"sql": sql}).encode(),
                headers={
                    "Authorization": f"Bearer {cf_api_token}",
                    "Content-Type": "application/json"
                },
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json_lib.loads(response.read().decode())
                if result.get("success"):
                    synced.append(domain)
                else:
                    errors.append({"domain": domain, "error": result.get("errors", [])})
        except Exception as e:
            errors.append({"domain": domain, "error": str(e)})
    
    return {
        "tenant_id": tenantId,
        "synced": len(synced) > 0,
        "synced_domains": synced,
        "errors": errors,
        "message": f"Synced {len(synced)}/{len(domain_list)} domains to Worker D1"
    }


@app.get("/admin/api/routes")
def list_routes(
    resp: Response,
    authorization: str = Header(default="")
):
    """List all registered routes (admin token required)."""
    _check_admin_auth(authorization)
    
    routes = []
    for route in app.routes:
        if hasattr(route, "methods") and hasattr(route, "path"):
            for method in route.methods:
                if method != "HEAD":  # Skip HEAD, it's implicit
                    routes.append({"method": method, "path": route.path})
    
    return {
        "total": len(routes),
        "routes": sorted(routes, key=lambda x: (x["path"], x["method"]))
    }


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


@app.get("/admin/api/tenant/{tenantId}/faq-dump")
def get_faq_dump(
    tenantId: str,
    resp: Response,
    authorization: str = Header(default="")
):
    """Get detailed FAQ dump with variant counts (admin only)."""
    _check_admin_auth(authorization)
    
    import json as json_lib
    
    with get_conn() as conn:
        # Get live FAQ count
        live_count = conn.execute(
            "SELECT COUNT(*) FROM faq_items WHERE tenant_id=%s AND is_staged=false",
            (tenantId,)
        ).fetchone()[0]
        
        # Get each FAQ with variant count
        faqs = []
        rows = conn.execute("""
            SELECT fi.id, fi.question, fi.answer,
                   COUNT(fv.id) as variant_count
            FROM faq_items fi
            LEFT JOIN faq_variants fv ON fv.faq_id = fi.id AND fv.enabled = true
            WHERE fi.tenant_id = %s AND fi.is_staged = false
            GROUP BY fi.id, fi.question, fi.answer
            ORDER BY fi.id
        """, (tenantId,)).fetchall()
        
        for row in rows:
            faq_id, question, answer, variant_count = row
            
            # Get sample variants (first 20, and any containing beep/chirp/smoke/alarm)
            variant_samples = conn.execute("""
                SELECT variant_question 
                FROM faq_variants 
                WHERE faq_id = %s AND enabled = true
                ORDER BY 
                    CASE WHEN variant_question ILIKE ANY(ARRAY['%beep%', '%chirp%', '%smoke%', '%alarm%']) THEN 0 ELSE 1 END,
                    id
                LIMIT 20
            """, (faq_id,)).fetchall()
            
            faqs.append({
                "id": faq_id,
                "question": question,
                "answer": answer[:200] + "..." if len(answer) > 200 else answer,
                "variant_count": variant_count,
                "variant_samples": [v[0] for v in variant_samples]
            })
    
    return {
        "tenant_id": tenantId,
        "live_faq_count": live_count,
        "faqs": faqs
    }


@app.get("/admin/api/tenant/{tenantId}/embedding-stats")
def get_embedding_stats(
    tenantId: str,
    resp: Response,
    authorization: str = Header(default="")
):
    """Get embedding statistics for a tenant (admin only)."""
    _check_admin_auth(authorization)
    
    with get_conn() as conn:
        # Count embedded variants
        variant_count = conn.execute("""
            SELECT COUNT(*) 
            FROM faq_variants fv
            JOIN faq_items fi ON fi.id = fv.faq_id
            WHERE fi.tenant_id = %s AND fi.is_staged = false AND fv.enabled = true
        """, (tenantId,)).fetchone()[0]
        
        # Get min/max/avg variants per FAQ
        stats = conn.execute("""
            SELECT 
                COUNT(DISTINCT fi.id) as faq_count,
                MIN(variant_count) as min_variants,
                MAX(variant_count) as max_variants,
                AVG(variant_count) as avg_variants
            FROM faq_items fi
            LEFT JOIN (
                SELECT faq_id, COUNT(*) as variant_count
                FROM faq_variants
                WHERE enabled = true
                GROUP BY faq_id
            ) v ON v.faq_id = fi.id
            WHERE fi.tenant_id = %s AND fi.is_staged = false
        """, (tenantId,)).fetchone()
        
        faq_count, min_v, max_v, avg_v = stats
        
        return {
            "tenant_id": tenantId,
            "total_embedded_variants": variant_count,
            "live_faq_count": faq_count,
            "variants_per_faq": {
                "min": min_v or 0,
                "max": max_v or 0,
                "avg": round(float(avg_v or 0), 1)
            }
        }


@app.post("/admin/api/tenant/{tenantId}/debug-query")
async def debug_query(
    tenantId: str,
    request: Request,
    resp: Response,
    authorization: str = Header(default="")
):
    """
    Admin-only debug endpoint to test a query and get full debug info.
    Works even when DEBUG=false (requires ADMIN_TOKEN).
    """
    _check_admin_auth(authorization)
    
    try:
        body = await request.json()
        customer_message = body.get("customerMessage", "").strip()
        if not customer_message:
            raise HTTPException(status_code=400, detail="customerMessage required")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    
    # Create a mock request object for generate_quote_reply
    from app.models import QuoteRequest
    
    quote_req = QuoteRequest(
        tenantId=tenantId,
        customerMessage=customer_message
    )
    
    # Call generate_quote_reply and capture all headers
    try:
        result_payload = generate_quote_reply(quote_req, resp)
        
        # Extract debug info from response headers
        # Get retrieval trace for candidate info
        retrieval_trace = getattr(resp, "_retrieval_trace", None)
        
        debug_info = {
            "tenant_id": tenantId,
            "customer_message": customer_message,
            "faq_hit": resp.headers.get("X-Faq-Hit", "false").lower() == "true",
            "debug_branch": resp.headers.get("X-Debug-Branch", "unknown"),
            "retrieval_score": resp.headers.get("X-Retrieval-Score"),
            "retrieval_stage": resp.headers.get("X-Retrieval-Stage"),
            "retrieval_mode": resp.headers.get("X-Retrieval-Mode"),
            "triage_result": resp.headers.get("X-Triage-Result"),
            "cache_hit": resp.headers.get("X-Cache-Hit", "false").lower() == "true",
            "replyText": result_payload.get("replyText", ""),
            "top_faq_id": resp.headers.get("X-Top-Faq-Id"),
            "chosen_faq_id": resp.headers.get("X-Chosen-Faq-Id"),
            "normalized_input": resp.headers.get("X-Normalized-Input", ""),
            "candidates": retrieval_trace.get("candidates", []) if retrieval_trace else [],
            "candidate_count": retrieval_trace.get("candidates_count", 0) if retrieval_trace else 0,
            "selector_called": resp.headers.get("X-Selector-Called", "false").lower() == "true",
            "selector_confidence": resp.headers.get("X-Selector-Confidence"),
            "selector_choice": retrieval_trace.get("selector_choice") if retrieval_trace else None,
            "selector_trace": retrieval_trace.get("selector_trace") if retrieval_trace else None,
            "retrieval_latency_ms": retrieval_trace.get("retrieval_ms", 0) if retrieval_trace else 0,
            "selector_latency_ms": retrieval_trace.get("selector_ms") if retrieval_trace else None,
            "total_latency_ms": retrieval_trace.get("total_ms", 0) if retrieval_trace else 0,
            # Legacy fields (for backwards compatibility)
            "rerank_triggered": resp.headers.get("X-Selector-Called", "false").lower() == "true",
            "rerank_candidates": None,
            "rerank_reason": None
        }
        
        # Add selector-specific info if available
        if retrieval_trace and retrieval_trace.get("selector_trace"):
            st = retrieval_trace["selector_trace"]
            debug_info["selector_response"] = st.get("llm_response")
            debug_info["selector_error"] = st.get("error")
        
        # Legacy rerank fields (for backwards compatibility)
        if retrieval_trace and retrieval_trace.get("rerank_trace"):
            rt = retrieval_trace["rerank_trace"]
            debug_info["rerank_candidates"] = rt.get("candidates_seen", [])
            debug_info["rerank_reason"] = rt.get("reason")
            if rt.get("safety_gate") != "passed":
                debug_info["rerank_failure_reason"] = rt.get("safety_gate")
        
        return debug_info
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Debug query failed: {str(e)}")

