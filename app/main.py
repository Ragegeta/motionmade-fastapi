from __future__ import annotations

import json
import re
import os
import smtplib
import time
import hashlib
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import List, Optional, Set
from datetime import datetime, timedelta

from fastapi import FastAPI, Header, HTTPException, Response, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from pgvector import Vector

from .settings import settings
from .guardrails import FALLBACK, violates_general_safety, classify_fact_domain, is_capability_question, is_logistics_question
from .openai_client import embed_text, chat_once
from .retrieval import retrieve_faq_answer
from .retriever import _invalidate_tenant_count_cache
from .db import get_conn
from .triage import triage_input
from .normalize import normalize_message
from .splitter import split_intents
from .cache import get_cached_result, cache_result, get_cache_stats
from .variant_expander import expand_faq_list

# Owner dashboard auth
try:
    import bcrypt
    from jose import jwt, JWTError
except ImportError:
    bcrypt = None
    jwt = None
    JWTError = Exception

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

# Serve widget.js at root for easy embedding (same file as /static/widget.js)
_widget_js_path = Path(__file__).resolve().parent / "static" / "widget.js"


@app.get("/widget.js", include_in_schema=False)
def serve_widget_js():
    """Serve the embeddable widget script."""
    if not _widget_js_path.exists():
        raise HTTPException(status_code=404, detail="Widget not found")
    return Response(
        content=_widget_js_path.read_text(encoding="utf-8"),
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
        },
    )


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
  business_type TEXT,
  contact_phone TEXT,
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

-- Create HNSW index for vector search (preferred, faster than ivfflat)
-- Falls back to ivfflat if HNSW not supported (pgvector < 0.5)
DO $$
BEGIN
    -- Try HNSW first (pgvector >= 0.5)
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c 
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = 'faq_variants_embedding_hnsw_idx' AND n.nspname = 'public'
    ) THEN
        BEGIN
            EXECUTE 'CREATE INDEX CONCURRENTLY IF NOT EXISTS faq_variants_embedding_hnsw_idx
                     ON faq_variants USING hnsw (variant_embedding vector_cosine_ops)
                     WHERE enabled = true';
        EXCEPTION WHEN OTHERS THEN
            -- HNSW not supported, create ivfflat instead
            IF NOT EXISTS (
                SELECT 1 FROM pg_class c 
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = 'faq_variants_embedding_ivfflat_idx' AND n.nspname = 'public'
            ) THEN
                EXECUTE 'CREATE INDEX CONCURRENTLY IF NOT EXISTS faq_variants_embedding_ivfflat_idx
                         ON faq_variants USING ivfflat (variant_embedding vector_cosine_ops)
                         WITH (lists = 100)
                         WHERE enabled = true';
            END IF;
        END;
    END IF;
END $$;

-- Drop old unfiltered index if it exists (replaced by filtered index above)
DROP INDEX IF EXISTS faq_variants_embedding_idx;

-- Index to help tenant filtering on faq_items
CREATE INDEX IF NOT EXISTS idx_faq_items_tenant_live 
ON faq_items(tenant_id) 
WHERE is_staged = false AND enabled = true;

-- Partitioned table for faq_variants (Phase 2: tenant partitioning for ANN index performance)
-- Parent table with LIST partitioning by tenant_id
-- Note: PRIMARY KEY must include partition key (tenant_id) for partitioned tables
CREATE TABLE IF NOT EXISTS faq_variants_p (
  id BIGINT NOT NULL DEFAULT nextval('faq_variants_p_id_seq'),
  tenant_id TEXT NOT NULL,
  faq_id BIGINT NOT NULL REFERENCES faq_items(id) ON DELETE CASCADE,
  variant_question TEXT NOT NULL,
  variant_embedding vector(1536) NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT true,
  updated_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (tenant_id, id)
) PARTITION BY LIST (tenant_id);

-- Create sequence for id generation (shared across partitions)
CREATE SEQUENCE IF NOT EXISTS faq_variants_p_id_seq;

-- Helper function to ensure partition exists for a tenant
CREATE OR REPLACE FUNCTION ensure_faq_variants_partition(p_tenant_id TEXT)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_partition_name TEXT;
    v_sanitized_tenant TEXT;
BEGIN
    -- Sanitize tenant_id for partition name (lowercase, alnum + underscore only)
    v_sanitized_tenant := lower(regexp_replace(p_tenant_id, '[^a-z0-9_]', '_', 'g'));
    v_partition_name := 'faq_variants_p_' || v_sanitized_tenant;
    
    -- Check if partition exists
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = v_partition_name AND n.nspname = 'public'
    ) THEN
        -- Create partition
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I PARTITION OF faq_variants_p
            FOR VALUES IN (%L)
        ', v_partition_name, p_tenant_id);
        
        -- Create ivfflat index on this partition
        EXECUTE format('
            CREATE INDEX IF NOT EXISTS %I
            ON %I USING ivfflat (variant_embedding vector_cosine_ops)
            WITH (lists = 100)
            WHERE enabled = true
        ', v_partition_name || '_embedding_idx', v_partition_name);
        
        -- Create supporting indexes
        EXECUTE format('
            CREATE INDEX IF NOT EXISTS %I
            ON %I (faq_id)
        ', v_partition_name || '_faq_id_idx', v_partition_name);
    END IF;
END;
$$;

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

CREATE TABLE IF NOT EXISTS tenant_owners (
  id SERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  last_login TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS tenant_owners_tenant_id_idx ON tenant_owners(tenant_id);
CREATE UNIQUE INDEX IF NOT EXISTS tenant_owners_email_key ON tenant_owners(email);

CREATE TABLE IF NOT EXISTS faq_suggestions (
  id SERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  suggested_question TEXT NOT NULL,
  suggested_answer TEXT,
  status TEXT DEFAULT 'pending',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  reviewed_at TIMESTAMPTZ,
  reviewer_note TEXT
);

CREATE INDEX IF NOT EXISTS faq_suggestions_tenant_idx ON faq_suggestions(tenant_id);
CREATE INDEX IF NOT EXISTS faq_suggestions_status_idx ON faq_suggestions(status);

CREATE TABLE IF NOT EXISTS query_stats (
  id SERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  query_date DATE NOT NULL DEFAULT CURRENT_DATE,
  hour_of_day INT,
  total_queries INT DEFAULT 0,
  successful_matches INT DEFAULT 0,
  fallback_count INT DEFAULT 0,
  avg_confidence REAL,
  UNIQUE(tenant_id, query_date, hour_of_day)
);

CREATE INDEX IF NOT EXISTS query_stats_tenant_date_idx ON query_stats(tenant_id, query_date);

CREATE TABLE IF NOT EXISTS query_log (
    id SERIAL PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    customer_question TEXT NOT NULL,
    matched_faq TEXT,
    confidence REAL,
    retrieval_path TEXT,
    was_fallback BOOLEAN DEFAULT FALSE,
    answer_given TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_query_log_tenant_created ON query_log (tenant_id, created_at DESC);

DO $$
BEGIN
  ALTER TABLE query_log ADD COLUMN answer_given TEXT;
EXCEPTION
  WHEN duplicate_column THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS demos (
  slug TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL UNIQUE REFERENCES tenants(id) ON DELETE CASCADE,
  business_name TEXT NOT NULL,
  business_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS demos_tenant_id_idx ON demos(tenant_id);

CREATE TABLE IF NOT EXISTS outreach_log (
  id BIGSERIAL PRIMARY KEY,
  to_email TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  sent_at TIMESTAMPTZ DEFAULT NOW(),
  status TEXT NOT NULL DEFAULT 'sent',
  lead_name TEXT
);
CREATE INDEX IF NOT EXISTS outreach_log_sent_at_idx ON outreach_log(sent_at DESC);

CREATE TABLE IF NOT EXISTS leads (
  id BIGSERIAL PRIMARY KEY,
  trade_type TEXT NOT NULL,
  suburb TEXT NOT NULL,
  business_name TEXT,
  website TEXT,
  email TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  audit_score INTEGER,
  audit_details JSONB,
  preview_url TEXT,
  preview_demo_id TEXT,
  email_subject TEXT,
  email_body TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS leads_status_idx ON leads(status);
CREATE INDEX IF NOT EXISTS leads_trade_suburb_idx ON leads(trade_type, suburb);
CREATE INDEX IF NOT EXISTS leads_created_idx ON leads(created_at DESC);

CREATE TABLE IF NOT EXISTS autopilot_log (
  id BIGSERIAL PRIMARY KEY,
  phase TEXT NOT NULL,
  message TEXT NOT NULL,
  detail JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS autopilot_log_created_idx ON autopilot_log(created_at DESC);

CREATE TABLE IF NOT EXISTS contact_submissions (
  id SERIAL PRIMARY KEY,
  name TEXT,
  business TEXT,
  email TEXT,
  phone TEXT,
  business_type TEXT,
  message TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS contact_submissions_created_idx ON contact_submissions(created_at DESC);
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


def _get_tenant_contact(tenant_id: str) -> tuple:
    """Return (display_name, contact_phone) for a tenant. Used for fallback/greeting messages."""
    if not tenant_id:
        return ("this business", "")
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT name, contact_phone FROM tenants WHERE id = %s",
                (tenant_id.strip(),),
            ).fetchone()
        if row:
            name = (row[0] or tenant_id).strip()
            phone = (row[1] or "").strip() if len(row) > 1 else ""
            return (name, phone)
    except Exception:
        pass
    return (tenant_id, "")


def _get_tenant_name_and_type(tenant_id: str) -> tuple:
    """Return (display_name, business_type) for off-topic check. business_type defaults to 'general'."""
    if not tenant_id:
        return ("this business", "general")
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT name, COALESCE(business_type, 'general') FROM tenants WHERE id = %s",
                (tenant_id.strip(),),
            ).fetchone()
        if row:
            name = (row[0] or tenant_id).strip()
            btype = (row[1] or "general").strip() or "general"
            return (name, btype)
    except Exception:
        pass
    return (tenant_id, "general")


# Off-topic check cache: (tenant_id, question_lower) -> (is_off_topic: bool, timestamp)
_off_topic_cache: dict = {}
_OFF_TOPIC_CACHE_TTL = 3600  # 1 hour


def _is_off_topic(
    tenant_id: str,
    question: str,
    business_name: str,
    business_type: str,
    matched_faq: str,
    confidence: float,
) -> bool:
    """Check if the customer question is unrelated to this business. Only runs when confidence < 0.85. Fail-open."""
    if confidence >= 0.85:
        return False
    cache_key = (tenant_id or "", (question or "").strip().lower()[:200])
    now = time.time()
    if cache_key in _off_topic_cache:
        cached_val, ts = _off_topic_cache[cache_key]
        if now - ts < _OFF_TOPIC_CACHE_TTL:
            return cached_val
    try:
        system = f"""You are a relevance checker for {business_name} ({business_type}).
This business has FAQs about their services. A customer asked a question on their website.
Decide if the customer's question is RELEVANT to this type of business.

Reply ONLY with "relevant" or "off-topic".

Examples for a cleaning business:
- "how much for a clean" → relevant
- "do you sell cars" → off-topic
- "what areas" → relevant
- "whats the weather" → off-topic
- "can i book online" → relevant
- "how do i make a website" → off-topic"""
        if (matched_faq or "").strip() in ("(no match)", "(no match found)", ""):
            user = f'Customer asked: "{question}"\nNo FAQ matched this question.\nIs this relevant to {business_name} ({business_type})?'
        else:
            user = f'Customer asked: "{question}"\nBest FAQ match: "{matched_faq}"\nIs this relevant to {business_name} ({business_type})?'
        reply = chat_once(
            system,
            user,
            temperature=0,
            max_tokens=10,
            timeout=2.0,
            model="gpt-4o-mini",
        )
        result = (reply or "").strip().lower()
        is_off = "off-topic" in result
        _off_topic_cache[cache_key] = (is_off, now)
        return is_off
    except Exception:
        return False  # fail open


def _hash_text(text: str) -> str:
    """Generate a short hash for privacy-safe logging. Returns empty string for empty input."""
    if not text:
        return ""
    # Use SHA256 and take first 16 chars for a short, collision-resistant hash
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


def _set_timing_headers(req: Request, resp: Response, timings: dict, cache_hit: bool):
    """Set timing headers if admin-gated debug mode is enabled.
    
    Requires:
    - X-Debug-Timings: 1 header in request
    - Valid admin auth (Bearer ADMIN_TOKEN)
    
    Otherwise, no timing headers are emitted. Always sets X-Debug-Timing-Gate
    header to indicate why timing headers weren't emitted (for debugging).
    """
    # Check for X-Debug-Timings header (case-insensitive)
    # FastAPI/Starlette headers are case-insensitive, try both common forms
    debug_timings = req.headers.get("x-debug-timings") or req.headers.get("X-Debug-Timings") or ""
    debug_timings = debug_timings.strip()
    if not debug_timings or debug_timings != "1":
        # Missing header - don't emit timing headers or gate header
        # (only emit gate header when X-Debug-Timings is present)
        return
    
    # Parse Authorization header robustly (case-insensitive Bearer, handle spaces)
    # FastAPI/Starlette headers are case-insensitive, try both common forms
    authorization_raw = req.headers.get("authorization") or req.headers.get("Authorization") or ""
    authorization_raw = authorization_raw.strip()
    if not authorization_raw:
        resp.headers["X-Debug-Timing-Gate"] = "missing_auth"
        return
    
    # Extract Bearer token (case-insensitive)
    auth_parts = authorization_raw.split(None, 1)  # Split on whitespace, max 1 split
    if len(auth_parts) != 2:
        resp.headers["X-Debug-Timing-Gate"] = "bad_auth"
        return
    
    auth_scheme = auth_parts[0].strip().lower()
    auth_token = auth_parts[1].strip()
    
    if auth_scheme != "bearer":
        resp.headers["X-Debug-Timing-Gate"] = "bad_auth"
        return
    
    # Compare token with ADMIN_TOKEN (exact match after stripping)
    if auth_token != settings.ADMIN_TOKEN:
        resp.headers["X-Debug-Timing-Gate"] = "bad_auth"
        return
    
    # Both conditions met: emit timing headers
    resp.headers["X-Debug-Timing-Gate"] = "ok"
    resp.headers["X-Timing-Triage"] = str(timings["triage_ms"])
    resp.headers["X-Timing-Normalize"] = str(timings["normalize_split_ms"])
    resp.headers["X-Timing-Embed"] = str(timings["embedding_ms"])
    resp.headers["X-Timing-Retrieval"] = str(timings["retrieval_ms"])
    
    # Fine-grained retrieval timing headers (from retrieval_trace if available)
    retrieval_trace = getattr(resp, "_retrieval_trace", None)
    if retrieval_trace:
        if retrieval_trace.get("retrieval_db_ms") is not None:
            resp.headers["X-Timing-Retrieval-DB"] = str(retrieval_trace["retrieval_db_ms"])
        if retrieval_trace.get("retrieval_db_fts_ms") is not None:
            resp.headers["X-Timing-Retrieval-FTS"] = str(retrieval_trace["retrieval_db_fts_ms"])
        if retrieval_trace.get("retrieval_db_vector_ms") is not None:
            resp.headers["X-Timing-Retrieval-Vector"] = str(retrieval_trace["retrieval_db_vector_ms"])
        if retrieval_trace.get("retrieval_db_tenant_count_ms") is not None:
            resp.headers["X-Timing-Retrieval-Tenant-Count"] = str(retrieval_trace["retrieval_db_tenant_count_ms"])
        if retrieval_trace.get("retrieval_db_cache_read_ms") is not None:
            resp.headers["X-Timing-Retrieval-Cache-Read"] = str(retrieval_trace["retrieval_db_cache_read_ms"])
        if retrieval_trace.get("retrieval_db_cache_write_ms") is not None:
            resp.headers["X-Timing-Retrieval-Cache-Write"] = str(retrieval_trace["retrieval_db_cache_write_ms"])
        if retrieval_trace.get("retrieval_rerank_ms") is not None:
            resp.headers["X-Timing-Retrieval-Rerank"] = str(retrieval_trace["retrieval_rerank_ms"])
        
        # TASK C: Add counters to timing headers
        if retrieval_trace.get("used_fts_only") is not None:
            resp.headers["X-Retrieval-Used-FTS-Only"] = "1" if retrieval_trace["used_fts_only"] else "0"
        if retrieval_trace.get("ran_vector") is not None:
            resp.headers["X-Retrieval-Ran-Vector"] = "1" if retrieval_trace["ran_vector"] else "0"
        if retrieval_trace.get("fts_candidate_count") is not None:
            resp.headers["X-Retrieval-FTS-Candidates"] = str(retrieval_trace["fts_candidate_count"])
        if retrieval_trace.get("vector_k") is not None:
            resp.headers["X-Retrieval-Vector-K"] = str(retrieval_trace["vector_k"])
    resp.headers["X-Timing-Rewrite"] = str(timings["rewrite_ms"])
    resp.headers["X-Timing-LLM"] = str(timings["llm_ms"])
    if "general_llm_ms" in timings:
        resp.headers["X-Timing-General-LLM"] = str(timings["general_llm_ms"])
    if "general_safety_ms" in timings:
        resp.headers["X-Timing-General-Safety"] = str(timings["general_safety_ms"])
    if "general_total_ms" in timings:
        resp.headers["X-Timing-General-Total"] = str(timings["general_total_ms"])
    resp.headers["X-Timing-Total"] = str(timings["total_ms"])
    resp.headers["X-Cache-Hit"] = "true" if cache_hit else "false"
    
    # X-Retrieval-Stage is already set by the endpoint if available


def _log_query_log(
    tenant_id: str,
    customer_question: str,
    matched_faq_id: Optional[int],
    confidence: Optional[float],
    retrieval_path: Optional[str],
    was_fallback: bool,
    answer_given: Optional[str] = None,
):
    """Log individual query for owner dashboard. Fire-and-forget; never breaks response."""
    q_preview = ((customer_question or "").strip() or "")[:50]
    print(f"[QUERY_LOG] Writing: tenant={tenant_id} q={q_preview!r}")
    try:
        matched_faq_text = None
        with get_conn() as conn:
            if matched_faq_id:
                row = conn.execute(
                    "SELECT question FROM faq_items WHERE id = %s", (matched_faq_id,)
                ).fetchone()
                if row:
                    matched_faq_text = (row[0] or "").strip() or None
            conn.execute(
                """INSERT INTO query_log (tenant_id, customer_question, matched_faq, confidence, retrieval_path, was_fallback, answer_given)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (tenant_id, (customer_question or "").strip() or "", matched_faq_text, confidence, retrieval_path or None, was_fallback, (answer_given or "").strip() or None),
            )
            conn.commit()
    except Exception as e:
        print(f"[QUERY_LOG] ERROR: {e}")


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
    selector_latency_ms: Optional[int] = None,
    retrieval_path: Optional[str] = None,
    answer_given: Optional[str] = None,
):
    """Log request telemetry for analytics. Privacy-safe: stores only lengths and hashes, not raw text."""
    # Telemetry: only columns that exist in schema (candidate_count, retrieval_mode, etc. may not exist)
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
                    rewrite_triggered, latency_ms)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (tenant_id, query_len, normalized_len, query_hash, normalized_hash, intent_count,
                 debug_branch, faq_hit, top_faq_id, retrieval_score, rewrite_triggered, latency_ms)
            )
            succ = 1 if faq_hit else 0
            fall = 0 if faq_hit else 1
            conf = float(retrieval_score) if retrieval_score is not None else None
            conn.execute(
                """INSERT INTO query_stats (tenant_id, query_date, hour_of_day, total_queries, successful_matches, fallback_count, avg_confidence)
                   VALUES (%s, CURRENT_DATE, EXTRACT(HOUR FROM now())::integer, 1, %s, %s, %s)
                   ON CONFLICT (tenant_id, query_date, hour_of_day) DO UPDATE SET
                     total_queries = query_stats.total_queries + 1,
                     successful_matches = query_stats.successful_matches + EXCLUDED.successful_matches,
                     fallback_count = query_stats.fallback_count + EXCLUDED.fallback_count,
                     avg_confidence = (COALESCE(query_stats.avg_confidence, 0) * query_stats.total_queries + COALESCE(EXCLUDED.avg_confidence, 0)) / (query_stats.total_queries + 1)""",
                (tenant_id, succ, fall, conf)
            )
            conn.commit()
    except Exception as e:
        print(f"[TELEMETRY] ERROR: {e}")
    # Owner dashboard query log: always attempt so query_log is populated even if telemetry fails
    try:
        _log_query_log(
            tenant_id=tenant_id,
            customer_question=query_text,
            matched_faq_id=int(top_faq_id) if top_faq_id is not None else None,
            confidence=float(retrieval_score) if retrieval_score is not None else None,
            retrieval_path=retrieval_path,
            was_fallback=not faq_hit,
            answer_given=answer_given,
        )
    except Exception as e:
        print(f"[QUERY_LOG] ERROR (from telemetry): {e}")


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


_GENERAL_PATTERNS = [
    r"\bwhat is (the )?(sun|moon|sky|weather|rain|snow|clouds)\b",
    r"\btell me a joke\b",
    r"\btell me about\b",
    r"\bwho is\b",
    r"\bwhat is\b",
    r"\bdefine\b",
    r"\bexplain\b",
    r"\bwhy is\b",
    r"\bhow does\b",
    r"\bhi\b",
    r"\bhello\b",
    r"\bthanks\b",
    r"\bthank you\b",
]

_BUSINESS_KEYWORDS = [
    "price", "pricing", "cost", "quote", "estimate", "booking", "book", "appointment",
    "availability", "available", "schedule", "hours", "opening", "closing",
    "address", "location", "contact", "phone", "email",
    "service", "services", "business", "company", "guarantee", "warranty",
    "payment", "invoice", "refund", "cancel", "discount",
]

_BUSINESS_INTENT_PHRASES = [
    "what do you do",
    "how does it work",
    "what is motionmade",
    "who is this for",
]


def _is_obvious_general_question(msg: str) -> bool:
    t = (msg or "").strip().lower()
    if not t:
        return False

    # Block anything that looks business-related or capability/logistics
    if any(p in t for p in _BUSINESS_INTENT_PHRASES):
        return False
    if classify_fact_domain(t) != "none":
        return False
    if is_capability_question(t) or is_logistics_question(t):
        return False
    if any(k in t for k in _BUSINESS_KEYWORDS):
        return False

    # Simple math and obvious general prompts
    if re.search(r"\b\d+\s*[\+\-\*/]\s*\d+\b", t):
        return True
    return any(re.search(p, t) for p in _GENERAL_PATTERNS)

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
    resp.headers["X-Fact-Domain"] = domain or "none"
    resp.headers["X-Fact-Gate-Hit"] = "true" if domain != "none" else "false"

    resp.headers["X-Faq-Hit"] = "false"
    resp.headers["X-Debug-Branch"] = "error"
    return domain


def _split_schema_statements(sql: str) -> List[str]:
    """Split SCHEMA_SQL into statements, respecting dollar-quoted blocks ($$ ... $$ or $tag$ ... $tag$).
    Semicolons inside dollar-quoted content do not end the statement.
    """
    statements = []
    pos = 0
    n = len(sql)
    while pos < n:
        # Skip whitespace and single-line comments
        while pos < n and (sql[pos] in ' \t\n\r' or (sql[pos:pos+2] == '--' and (pos == 0 or sql[pos-1] in '\n\r'))):
            if pos < n and sql[pos:pos+2] == '--':
                while pos < n and sql[pos] != '\n':
                    pos += 1
            else:
                pos += 1
        if pos >= n:
            break
        start = pos
        i = pos
        while i < n:
            if sql[i] == '$':
                # Dollar-quoted string: $ or $tag$
                delim_start = i
                i += 1
                if i >= n:
                    break
                # Optional tag (word chars)
                while i < n and (sql[i].isalnum() or sql[i] == '_'):
                    i += 1
                if i < n and sql[i] == '$':
                    i += 1
                    delim = sql[delim_start:i]
                    # Find closing same delimiter
                    close = sql.find(delim, i)
                    if close == -1:
                        i = n
                        break
                    i = close + len(delim)
                    continue
            if sql[i] == ';':
                # Statement terminator (we're outside dollar-quoted)
                stmt = sql[start:i].strip()
                if stmt and not stmt.startswith('--'):
                    statements.append(stmt)
                pos = i + 1
                break
            i += 1
        else:
            # No semicolon found - rest is one statement (or trailing comment)
            stmt = sql[start:].strip()
            if stmt and not stmt.startswith('--'):
                statements.append(stmt)
            break
    return statements


@app.on_event("startup")
def _startup():
    """Initialize database schema on startup. Non-blocking - failures don't prevent startup."""
    # Run DB initialization in background thread to avoid blocking startup
    # If DB is slow/unavailable, app still starts and can serve /ping
    import threading
    
    def init_db():
        try:
            statements = _split_schema_statements(SCHEMA_SQL)
            for i, stmt in enumerate(statements):
                stmt = stmt.strip()
                if not stmt or stmt.startswith('--'):
                    continue
                try:
                    with get_conn() as conn:
                        conn.execute(stmt)
                        conn.commit()
                except Exception as e:
                    # Extract table/object name from statement for better error reporting
                    obj_name = "unknown"
                    if "CREATE TABLE" in stmt.upper():
                        match = re.search(r'CREATE TABLE.*?(\w+)', stmt, re.IGNORECASE)
                        if match:
                            obj_name = match.group(1)
                    elif "CREATE FUNCTION" in stmt.upper() or "CREATE OR REPLACE FUNCTION" in stmt.upper():
                        match = re.search(r'FUNCTION.*?(\w+)', stmt, re.IGNORECASE)
                        if match:
                            obj_name = match.group(1)
                    elif "CREATE SEQUENCE" in stmt.upper():
                        match = re.search(r'SEQUENCE.*?(\w+)', stmt, re.IGNORECASE)
                        if match:
                            obj_name = match.group(1)
                    elif "DO $$" in stmt or "DO $" in stmt:
                        obj_name = "do_block"
                    print(f"[schema_init] Failed to create {obj_name}: {str(e)}")
                    print(f"[schema_init] Statement: {stmt[:200]}...")
                    # Continue with other statements - each runs in its own transaction
            
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

            # Add business_type to tenants if missing
            try:
                with get_conn() as conn:
                    conn.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS business_type TEXT")
                    conn.commit()
            except Exception:
                try:
                    with get_conn() as conn:
                        conn.execute("ALTER TABLE tenants ADD COLUMN business_type TEXT")
                        conn.commit()
                except Exception:
                    pass  # Column may already exist

            # Seed business_type for known tenants (idempotent)
            try:
                with get_conn() as conn:
                    for tid, btype in [
                        ("demo_cleaner", "cleaner"),
                        ("brissy_cleaners", "cleaner"),
                        ("sparkys_electrical", "electrician"),
                        ("muassis", "founder_program"),
                    ]:
                        conn.execute(
                            "UPDATE tenants SET business_type = %s WHERE id = %s",
                            (btype, tid),
                        )
                    conn.commit()
            except Exception:
                pass

            # Add contact_phone to tenants if missing
            try:
                with get_conn() as conn:
                    conn.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS contact_phone TEXT")
                    conn.commit()
            except Exception:
                try:
                    with get_conn() as conn:
                        conn.execute("ALTER TABLE tenants ADD COLUMN contact_phone TEXT")
                        conn.commit()
                except Exception:
                    pass
                
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

                # Ensure partition exists
                conn.execute("SELECT ensure_faq_variants_partition(%s)", (tenantId,))
                
                for vq in variants:
                    v_emb = embed_text(vq)
                    # Insert into old table
                    conn.execute(
                        "INSERT INTO faq_variants (faq_id, variant_question, variant_embedding, enabled) "
                        "VALUES (%s,%s,%s,true)",
                        (faq_id, vq, Vector(v_emb)),
                    )
                    # Insert into partitioned table
                    conn.execute(
                        "INSERT INTO faq_variants_p (tenant_id, faq_id, variant_question, variant_embedding, enabled) "
                        "VALUES (%s,%s,%s,%s,true)",
                        (tenantId, faq_id, vq, Vector(v_emb)),
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
    # Allow general responses on FAQ miss; safety is handled post-reply.
    return False


@app.get("/api/v2/tenant/{tenant_id}/suggested-questions")
def get_suggested_questions(tenant_id: str):
    """Return top 5 FAQ questions for the widget (first 5 by ID, live only). CORS allowed for widget embed."""
    tid = (tenant_id or "").strip()
    if not tid:
        return {"questions": []}
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """
                SELECT question FROM faq_items
                WHERE tenant_id = %s AND is_staged = false AND enabled = true
                ORDER BY id ASC
                LIMIT 5
                """,
                (tid,),
            ).fetchall()
        questions = [row[0] for row in rows if row and row[0]]
        return {"questions": questions}
    except Exception:
        return {"questions": []}


@app.post("/api/v2/contact-form")
async def contact_form(request: Request):
    """Receive contact form submissions from the landing page."""
    data = await request.json()

    # Log clearly
    print(f"\n{'='*50}")
    print(f"🔔 NEW LEAD")
    print(f"  Name: {data.get('name', '')}")
    print(f"  Business: {data.get('business', '')}")
    print(f"  Email: {data.get('email', '')}")
    print(f"  Phone: {data.get('phone', '')}")
    print(f"  Type: {data.get('type', '')}")
    print(f"  Message: {data.get('message', '')}")
    print(f"{'='*50}\n")

    # Store in database
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO contact_submissions (name, business, email, phone, business_type, message)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    data.get("name"),
                    data.get("business"),
                    data.get("email"),
                    data.get("phone"),
                    data.get("type"),
                    data.get("message"),
                ),
            )
            conn.commit()
    except Exception as e:
        print(f"[CONTACT] DB error: {e}")

    return {"ok": True}


@app.post("/api/v2/generate-quote-reply")
def generate_quote_reply(req: QuoteRequest, resp: Response, request: Request):
    _start_time = time.monotonic()
    tenant_id = (req.tenantId or "").strip()
    msg = (req.customerMessage or "").strip()
    tenant_name, tenant_phone = _get_tenant_contact(tenant_id)

    def _fallback_text() -> str:
        if tenant_phone:
            return f"We don't have an answer for that one. Contact {tenant_name} on {tenant_phone} for help."
        return f"We don't have an answer for that one. Contact {tenant_name} directly for help."

    def _wrong_service_text() -> str:
        return f"That's not something {tenant_name} handles. Contact them directly for help."

    def _clarify_text() -> str:
        return "I didn't catch that. Try asking about our pricing, services, or how to book."

    # Greeting: direct prompt, no chatbot tone
    if msg.lower().strip() in ("hi", "hello", "hey"):
        resp.headers["X-Response-Time"] = f"{time.monotonic() - _start_time:.3f}s"
        resp.headers["X-Retrieval-Path"] = "fallback"
        resp.headers["X-Debug-Branch"] = "greeting"
        resp.headers["X-Faq-Hit"] = "false"
        payload = _base_payload()
        payload["replyText"] = f"Ask me a question about {tenant_name} — like pricing, services, or how to book."
        timings = {"triage_ms": 0, "normalize_split_ms": 0, "embedding_ms": 0, "retrieval_ms": 0, "rewrite_ms": 0, "llm_ms": 0, "general_llm_ms": 0, "general_safety_ms": 0, "general_total_ms": 0, "total_ms": int((time.time() - _start_time) * 1000)}
        _set_timing_headers(request, resp, timings, False)
        _log_telemetry(tenant_id=tenant_id, query_text=msg, normalized_text=msg, intent_count=0, debug_branch="greeting", faq_hit=False, top_faq_id=None, retrieval_score=None, rewrite_triggered=False, latency_ms=timings["total_ms"], retrieval_path="fallback", answer_given=payload["replyText"])
        return payload

    # Timing breakdown
    timings = {
        "triage_ms": 0,
        "normalize_split_ms": 0,
        "embedding_ms": 0,
        "retrieval_ms": 0,
        "rewrite_ms": 0,
        "llm_ms": 0,
        "general_llm_ms": 0,
        "general_safety_ms": 0,
        "general_total_ms": 0,
        "total_ms": 0
    }
    _cache_hit = False

    # === TRIAGE ===
    _t0 = time.time()
    triage_result, should_continue = triage_input(msg)
    timings["triage_ms"] = int((time.time() - _t0) * 1000)
    resp.headers["X-Triage-Result"] = triage_result or "pass"
    
    if not should_continue:
        resp.headers["X-Response-Time"] = f"{time.monotonic() - _start_time:.3f}s"
        resp.headers["X-Retrieval-Path"] = "fallback"
        resp.headers["X-Debug-Branch"] = "clarify"
        resp.headers["X-Faq-Hit"] = "false"
        payload = _base_payload()
        payload["replyText"] = _clarify_text()
        timings["total_ms"] = int((time.time() - _start_time) * 1000)
        _set_timing_headers(request, resp, timings, _cache_hit)
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
            latency_ms=timings["total_ms"],
            retrieval_path=resp.headers.get("X-Retrieval-Path") or "fallback",
            answer_given=payload["replyText"],
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

    def _respond_general(ok_branch: str, fallback_branch: str) -> dict:
        _t0 = time.time()
        _general_start = _t0
        try:
            system = (
                "Answer this question helpfully and professionally. Keep it brief. "
                "Do not ask follow-up questions. Do not include pricing, guarantees, "
                "or business-specific promises."
            )
            reply = chat_once(
                system,
                msg,
                temperature=0.4,
                max_tokens=150,
                timeout=8,
                model="gpt-3.5-turbo",
            )
            timings["llm_ms"] = int((time.time() - _t0) * 1000)
            timings["general_llm_ms"] = timings["llm_ms"]
        except Exception:
            timings["llm_ms"] = int((time.time() - _t0) * 1000)
            timings["general_llm_ms"] = timings["llm_ms"]
            resp.headers["X-Debug-Branch"] = "error"
            resp.headers["X-Faq-Hit"] = "false"
            payload["replyText"] = _fallback_text()
            timings["general_total_ms"] = int((time.time() - _general_start) * 1000)
            timings["total_ms"] = int((time.time() - _start_time) * 1000)
            _set_timing_headers(request, resp, timings, _cache_hit)
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
                latency_ms=timings["total_ms"],
                retrieval_path=resp.headers.get("X-Retrieval-Path") or "fallback",
                answer_given=payload["replyText"],
            )
            return payload

        _t0 = time.time()
        if violates_general_safety(reply):
            timings["general_safety_ms"] = int((time.time() - _t0) * 1000)
            resp.headers["X-Debug-Branch"] = fallback_branch
            resp.headers["X-Faq-Hit"] = "false"
            payload["replyText"] = _fallback_text()
            timings["general_total_ms"] = int((time.time() - _general_start) * 1000)
            timings["total_ms"] = int((time.time() - _start_time) * 1000)
            _set_timing_headers(request, resp, timings, _cache_hit)
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
                retrieval_path=resp.headers.get("X-Retrieval-Path") or "fallback",
                answer_given=payload["replyText"],
            )
            return payload

        timings["general_safety_ms"] = int((time.time() - _t0) * 1000)
        resp.headers["X-Debug-Branch"] = ok_branch
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = reply
        timings["general_total_ms"] = int((time.time() - _general_start) * 1000)
        timings["total_ms"] = int((time.time() - _start_time) * 1000)
        _set_timing_headers(request, resp, timings, _cache_hit)
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
            retrieval_path=resp.headers.get("X-Retrieval-Path") or "fallback",
            answer_given=payload["replyText"],
        )
        return payload

    # -----------------------------
    # Fast path: obvious general questions skip retrieval
    # -----------------------------
    if _is_obvious_general_question(primary_query):
        resp.headers["X-Response-Time"] = f"{time.monotonic() - _start_time:.3f}s"
        resp.headers["X-Retrieval-Path"] = "fallback"
        resp.headers["X-Retrieval-Stage"] = "skipped_general"
        resp.headers["X-Retrieval-Skip-Reason"] = "obvious_general"
        resp.headers["X-Cache-Hit"] = "false"
        return _respond_general("general_fast", "general_fast_fallback")

    # -----------------------------
    # Check cache first (only for FAQ hits)
    # But first check for wrong-service keywords to avoid returning cached wrong-service hits
    # -----------------------------
    # Quick wrong-service check before cache (import WRONG_SERVICE_KEYWORDS from retriever)
    try:
        from app.retriever import WRONG_SERVICE_KEYWORDS
    except Exception as e:
        WRONG_SERVICE_KEYWORDS = []
        resp.headers["X-Wrong-Service-Check"] = "error"
        resp.headers["X-Wrong-Service-Error"] = str(e)[:80]
    try:
        query_lower = primary_query.lower()
        wrong_service_keywords_in_query = [
            kw for kw in WRONG_SERVICE_KEYWORDS 
            if kw.lower() in query_lower
        ]
        # Skip cache if wrong-service keywords detected (let retriever handle it properly)
        skip_cache_for_wrong_service = len(wrong_service_keywords_in_query) > 0
    except Exception as e:
        resp.headers["X-Wrong-Service-Check"] = "error"
        resp.headers["X-Wrong-Service-Error"] = str(e)[:80]
        skip_cache_for_wrong_service = True
    
    cached_result = None
    if not skip_cache_for_wrong_service:
        cached_result = get_cached_result(tenant_id, primary_query)
    
    if cached_result:
        _cache_hit = True
        resp.headers["X-Cache-Hit"] = "true"
        resp.headers["X-Debug-Branch"] = cached_result.get("debug_branch") or "fact_hit"
        
        # HARD RULE: Never allow faq_hit=true when candidate_count==0
        # Default to 0 (not 1) to be safe - old cached results without candidate_count should be rejected
        cached_candidate_count = cached_result.get("candidates_count", 0)
        if cached_candidate_count == 0:
            resp.headers["X-Faq-Hit"] = "false"
            resp.headers["X-Candidate-Count"] = "0"
            # Don't return cached result if candidate_count is 0
            cached_result = None
        else:
            resp.headers["X-Faq-Hit"] = "true"
            resp.headers["X-Retrieval-Score"] = str(cached_result.get("retrieval_score", ""))
            if cached_result.get("top_faq_id"):
                resp.headers["X-Top-Faq-Id"] = str(cached_result["top_faq_id"])
            payload["replyText"] = cached_result["replyText"]
            resp.headers["X-Candidate-Count"] = str(cached_candidate_count)
            timings["total_ms"] = int((time.time() - _start_time) * 1000)
            resp.headers["X-Response-Time"] = f"{time.monotonic() - _start_time:.3f}s"
            resp.headers["X-Retrieval-Path"] = "cache"
            _set_timing_headers(request, resp, timings, _cache_hit)
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
                latency_ms=timings["total_ms"],
                retrieval_path=resp.headers.get("X-Retrieval-Path") or "cache",
                answer_given=payload["replyText"],
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
        
        # Set debug headers from trace (including response time and path for every request)
        elapsed = time.monotonic() - _start_time
        resp.headers["X-Response-Time"] = f"{elapsed:.3f}s"
        resp.headers["X-Retrieval-Path"] = retrieval_trace.get("retrieval_path", "fallback")
        resp.headers["X-Retrieval-Stage"] = retrieval_trace.get("stage") or "unknown"
        if retrieval_trace.get("top_score") is not None:
            resp.headers["X-Retrieval-Score"] = str(retrieval_trace.get("top_score", 0))
        resp.headers["X-Cache-Hit"] = str(retrieval_trace.get("cache_hit", False)).lower()
        resp.headers["X-Retrieval-Mode"] = retrieval_trace.get("retrieval_mode") or "unknown"
        resp.headers["X-Candidate-Count"] = str(retrieval_trace.get("candidates_count", 0))
        resp.headers["X-Selector-Called"] = "1" if retrieval_trace.get("selector_called", False) else "0"
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
        resp.headers["X-Accept-Reason"] = (retrieval_trace.get("accept_reason") or "")[:50]
        if retrieval_trace.get("vector_skip_reason"):
            resp.headers["X-Retrieval-Skip-Vector-Reason"] = retrieval_trace.get("vector_skip_reason")[:50]
        resp.headers["X-Retrieval-Used-FTS-Only"] = "1" if retrieval_trace.get("used_fts_only", False) else "0"
        resp.headers["X-Retrieval-Ran-Vector"] = "1" if retrieval_trace.get("ran_vector", False) else "0"
        resp.headers["X-Tenant-Faq-Count"] = str(retrieval_trace.get("tenant_faq_count", "?"))
        resp.headers["X-Small-Tenant-Check"] = str(retrieval_trace.get("small_tenant_check_result", "?"))
        resp.headers["X-FTS-Count-At-Check"] = str(retrieval_trace.get("fts_candidate_count_at_small_check", "?"))
        
        if retrieval_trace.get("rerank_trace"):
            rt = retrieval_trace["rerank_trace"]
            resp.headers["X-Rerank-Method"] = rt.get("method") or "none"
            resp.headers["X-Rerank-Ms"] = str(rt.get("duration_ms", 0))
            if rt.get("safety_gate"):
                resp.headers["X-Rerank-Gate"] = rt.get("safety_gate", "")[:50]
        if retrieval_trace.get("selector_confidence") is not None:
            resp.headers["X-Selector-Confidence"] = str(retrieval_trace["selector_confidence"])
        
        # Convert to hit/answer format
        hit = retrieval_result is not None
        ans = retrieval_result["answer"] if retrieval_result else None
        faq_id = retrieval_result["faq_id"] if retrieval_result else None
        score = retrieval_result["score"] if retrieval_result else retrieval_trace.get("top_score", 0)
        chosen_faq_id = retrieval_trace.get("chosen_faq_id") or faq_id
        
        # HARD RULE: Never allow faq_hit=true when candidate_count==0
        candidate_count = retrieval_trace.get("candidates_count", 0)
        # Also check merged_count as fallback (in case candidates_count isn't set)
        merged_count = retrieval_trace.get("merged_count", 0)
        actual_candidate_count = candidate_count if candidate_count > 0 else merged_count
        
        if actual_candidate_count == 0:
            hit = False
            retrieval_result = None
            ans = None
            faq_id = None
            # Update trace to reflect this
            retrieval_trace["candidates_count"] = 0
        
        if faq_id is not None:
            resp.headers["X-Top-Faq-Id"] = str(faq_id)
        if chosen_faq_id is not None:
            resp.headers["X-Chosen-Faq-Id"] = str(chosen_faq_id)
        
        resp.headers["X-Faq-Hit"] = str(hit).lower()

        if hit and ans:
            resp.headers["X-Off-Topic-Check"] = "false"  # default when we have a match
            # Off-topic gate: only when confidence < 0.85 (don't slow down high-confidence matches)
            if score < 0.85:
                tenant_name_ot, tenant_type = _get_tenant_name_and_type(tenant_id)
                if _is_off_topic(
                    tenant_id, msg, tenant_name_ot, tenant_type,
                    retrieval_result.get("question") or "",
                    float(score),
                ):
                    resp.headers["X-Off-Topic-Check"] = "true"
                    hit = False
                    ans = None
            resp.headers["X-Response-Time"] = f"{time.monotonic() - _start_time:.3f}s"
            stage = retrieval_result.get("stage", "embedding")
            if stage == "selector":
                resp.headers["X-Debug-Branch"] = "selector_hit"
            elif stage == "rerank":
                resp.headers["X-Debug-Branch"] = "rerank_hit"
            elif stage == "cache":
                resp.headers["X-Debug-Branch"] = "cache_hit"
            else:
                resp.headers["X-Debug-Branch"] = "fact_hit"
            
            if hit and ans:
                resp.headers["X-Off-Topic-Check"] = "false"
                payload["replyText"] = str(ans).strip()
                # Cache the result (only for FAQ hits) - already cached by retriever
                cache_result(tenant_id, primary_query, {
                    "replyText": payload["replyText"],
                    "debug_branch": resp.headers.get("X-Debug-Branch", "fact_hit"),
                    "retrieval_score": score,
                    "top_faq_id": faq_id
                })
                timings["total_ms"] = int((time.time() - _start_time) * 1000)
                _set_timing_headers(request, resp, timings, _cache_hit)
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
                    selector_latency_ms=retrieval_trace.get("selector_ms"),
                    retrieval_path=retrieval_trace.get("retrieval_path") or resp.headers.get("X-Retrieval-Path") or "fallback",
                    answer_given=payload["replyText"],
                )
                return payload
            # Off-topic: return fallback immediately (do not try rewrite)
            if resp.headers.get("X-Off-Topic-Check") == "true":
                resp.headers["X-Response-Time"] = f"{time.monotonic() - _start_time:.3f}s"
                resp.headers["X-Retrieval-Path"] = "fallback"
                resp.headers["X-Debug-Branch"] = "off_topic"
                resp.headers["X-Faq-Hit"] = "false"
                payload["replyText"] = _fallback_text()
                timings["total_ms"] = int((time.time() - _start_time) * 1000)
                _set_timing_headers(request, resp, timings, _cache_hit)
                _log_telemetry(
                    tenant_id=tenant_id,
                    query_text=msg,
                    normalized_text=normalized_msg,
                    intent_count=int(resp.headers.get("X-Intent-Count", "1")),
                    debug_branch="off_topic",
                    faq_hit=False,
                    top_faq_id=None,
                    retrieval_score=float(score) if score is not None else None,
                    rewrite_triggered=False,
                    latency_ms=timings["total_ms"],
                    retrieval_path="fallback",
                    answer_given=payload["replyText"],
                )
                return payload

        # 2) Miss -> rewrite for retrieval only (skip for wrong-service and gibberish to keep speed)
        resp.headers["X-Debug-Branch"] = "fact_rewrite_try"
        resp.headers["X-Rewrite-Triggered"] = "true"

        if "X-Retrieval-Score" in resp.headers:
            resp.headers["X-Retrieval-Score-Raw"] = resp.headers["X-Retrieval-Score"]
        if "X-Retrieval-Delta" in resp.headers:
            resp.headers["X-Retrieval-Delta-Raw"] = resp.headers["X-Retrieval-Delta"]
        if "X-Top-Faq-Id" in resp.headers:
            resp.headers["X-Top-Faq-Id-Raw"] = resp.headers["X-Top-Faq-Id"]

        rewrite = ""
        # Skip rewrite when retriever already rejected (wrong-service) — stay under 2s
        if retrieval_trace.get("stage") == "wrong_service_rejected":
            pass  # keep rewrite = ""
        else:
            # Skip expensive rewrite for gibberish (no spaces + long, or very low alpha ratio)
            _pq = primary_query.strip()
            _alpha = sum(1 for c in _pq if c.isalpha())
            _gibberish = (len(_pq) > 5 and " " not in _pq) or (len(_pq) > 4 and _pq and _alpha / len(_pq) < 0.5)
            if not _gibberish:
                _t0 = time.time()
                try:
                    system = (
                        "Rewrite the user message into a short FAQ-style query (max 12 words). "
                        "Preserve the meaning. Do not add or change any facts. "
                        "Do NOT invent numbers, prices, times, policies, or inclusions. "
                        "Output only the rewritten query text with no quotes or explanation."
                    )
                    rewrite = chat_once(system, f"Original customer message: {msg}", temperature=0.0, timeout=2.0).strip()
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
                resp.headers["X-Response-Time"] = f"{time.monotonic() - _start_time:.3f}s"
                resp.headers["X-Retrieval-Path"] = "llm-rewrite"
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
                _set_timing_headers(request, resp, timings, _cache_hit)
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
                    retrieval_path=resp.headers.get("X-Retrieval-Path") or "llm-rewrite",
                    answer_given=payload["replyText"],
                )
                return payload

    except Exception:
        # If retrieval pipeline errors, fail safe
        resp.headers["X-Response-Time"] = f"{time.monotonic() - _start_time:.3f}s"
        resp.headers["X-Retrieval-Path"] = "fallback"
        resp.headers["X-Debug-Branch"] = "error"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = _fallback_text()
        timings["total_ms"] = int((time.time() - _start_time) * 1000)
        _set_timing_headers(request, resp, timings, _cache_hit)
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
            latency_ms=timings["total_ms"],
            retrieval_path=resp.headers.get("X-Retrieval-Path") or "fallback",
            answer_given=payload["replyText"],
        )
        return payload

    # -----------------------------
    # Retrieval miss -> decide fallback vs general
    # -----------------------------
    # Wrong-service rejections must get FALLBACK only (no general LLM hallucination)
    _trace = getattr(resp, "_retrieval_trace", None) or {}
    if _trace.get("stage") == "wrong_service_rejected":
        resp.headers["X-Response-Time"] = f"{time.monotonic() - _start_time:.3f}s"
        resp.headers["X-Retrieval-Path"] = "fallback"
        resp.headers["X-Debug-Branch"] = "wrong_service"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = _wrong_service_text()
        timings["total_ms"] = int((time.time() - _start_time) * 1000)
        _set_timing_headers(request, resp, timings, _cache_hit)
        _log_telemetry(
            tenant_id=tenant_id,
            query_text=msg,
            normalized_text=normalized_msg,
            intent_count=int(resp.headers.get("X-Intent-Count", "1")),
            debug_branch="wrong_service",
            faq_hit=False,
            top_faq_id=None,
            retrieval_score=None,
            rewrite_triggered=resp.headers.get("X-Rewrite-Triggered", "false") == "true",
            latency_ms=timings["total_ms"],
            retrieval_path="fallback",
            answer_given=payload["replyText"],
        )
        return payload

    if _should_fallback_after_miss(msg, domain):
        resp.headers["X-Response-Time"] = f"{time.monotonic() - _start_time:.3f}s"
        resp.headers["X-Retrieval-Path"] = "fallback"
        resp.headers["X-Debug-Branch"] = "fact_miss"
        resp.headers["X-Faq-Hit"] = "false"
        payload["replyText"] = _fallback_text()
        timings["total_ms"] = int((time.time() - _start_time) * 1000)
        _set_timing_headers(request, resp, timings, _cache_hit)
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
            retrieval_path=resp.headers.get("X-Retrieval-Path") or "fallback",
            answer_given=payload["replyText"],
        )
        return payload

    # -----------------------------
    # General chat (professional tone, brief)
    # Off-topic check: if question is unrelated to this business, return fallback instead of general LLM
    # -----------------------------
    try:
        tenant_name_ot, tenant_type = _get_tenant_name_and_type(tenant_id)
        if _is_off_topic(
            tenant_id=tenant_id,
            question=msg,
            business_name=tenant_name_ot,
            business_type=tenant_type,
            matched_faq="(no match)",
            confidence=0.0,
        ):
            resp.headers["X-Response-Time"] = f"{time.monotonic() - _start_time:.3f}s"
            resp.headers["X-Retrieval-Path"] = "fallback"
            resp.headers["X-Debug-Branch"] = "off_topic_general"
            resp.headers["X-Off-Topic-Check"] = "true"
            resp.headers["X-Faq-Hit"] = "false"
            payload["replyText"] = _fallback_text()
            timings["total_ms"] = int((time.time() - _start_time) * 1000)
            _set_timing_headers(request, resp, timings, _cache_hit)
            _log_telemetry(
                tenant_id=tenant_id,
                query_text=msg,
                normalized_text=normalized_msg,
                intent_count=int(resp.headers.get("X-Intent-Count", "1")),
                debug_branch="off_topic_general",
                faq_hit=False,
                top_faq_id=None,
                retrieval_score=None,
                rewrite_triggered=resp.headers.get("X-Rewrite-Triggered", "false") == "true",
                latency_ms=timings["total_ms"],
                retrieval_path="fallback",
                answer_given=payload["replyText"],
            )
            return payload
    except Exception:
        pass  # fail open — let general path handle it

    resp.headers["X-Response-Time"] = f"{time.monotonic() - _start_time:.3f}s"
    resp.headers["X-Retrieval-Path"] = "fallback"
    return _respond_general("general_ok", "general_fallback")

@app.get("/ping")
def ping():
    """Simple liveness check - no DB, no external calls, just returns OK."""
    return {"ok": True}


@app.get("/api/health")
def health():
    """Health check endpoint with git SHA detection."""
    from .db import get_pool_status
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
    
    # Get connection pool status
    pool_status = get_pool_status()
    
    return {
        "ok": True,
        "gitSha": git_sha,
        "release": release,
        "deployed": git_sha != "unknown",
        "db_pool": pool_status
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


@app.get("/dashboard/login", response_class=HTMLResponse)
def dashboard_login_ui():
    """Serve owner dashboard login page."""
    html_path = Path(__file__).parent / "templates" / "dashboard_login.html"
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
        return HTMLResponse(content=html)
    return HTMLResponse(content="<h1>Dashboard login not found</h1>", status_code=404)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_ui():
    """Serve owner dashboard (auth is client-side via JWT)."""
    html_path = Path(__file__).parent / "templates" / "dashboard.html"
    if html_path.exists():
        html = html_path.read_text(encoding="utf-8")
        return HTMLResponse(content=html)
    return HTMLResponse(content="<h1>Dashboard not found</h1>", status_code=404)


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


# ---------- Owner dashboard auth ----------
OWNER_TOKEN_ALG = "HS256"
OWNER_TOKEN_EXP_HOURS = 24 * 7  # 7 days


def _hash_password(password: str) -> str:
    if not bcrypt:
        raise HTTPException(status_code=503, detail="Auth not configured (bcrypt missing)")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    if not bcrypt:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def _create_owner_token(owner_id: int, tenant_id: str, exp_hours: int = OWNER_TOKEN_EXP_HOURS) -> str:
    if not jwt or not settings.JWT_SECRET:
        raise HTTPException(status_code=503, detail="Auth not configured (JWT_SECRET missing)")
    exp = datetime.utcnow() + timedelta(hours=exp_hours)
    payload = {"sub": str(owner_id), "tenant_id": tenant_id, "exp": exp}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=OWNER_TOKEN_ALG)


def _decode_owner_token(token: str) -> Optional[dict]:
    if not jwt or not settings.JWT_SECRET:
        return None
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[OWNER_TOKEN_ALG])
    except JWTError:
        return None


def get_current_owner(authorization: str = Header(default="")):
    """Dependency: require valid owner JWT. Returns dict with owner_id, tenant_id."""
    if not authorization or not authorization.strip().startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization")
    token = authorization.strip().split(None, 1)[-1]
    payload = _decode_owner_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"owner_id": int(payload["sub"]), "tenant_id": payload["tenant_id"]}


class TenantCreate(BaseModel):
    id: str
    name: str
    business_type: Optional[str] = None
    contact_phone: Optional[str] = None


class DomainAdd(BaseModel):
    domain: str


class OwnerLogin(BaseModel):
    email: str
    password: str


class OwnerCreateBody(BaseModel):
    tenant_id: str
    email: str
    password: str
    display_name: Optional[str] = None


@app.post("/owner/login")
def owner_login(body: OwnerLogin):
    """Owner login: email + password -> JWT."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, tenant_id, password_hash, display_name FROM tenant_owners WHERE email = %s",
            (body.email.strip().lower(),),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    owner_id, tenant_id, password_hash, display_name = row
    if not _verify_password(body.password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    # Update last_login
    with get_conn() as conn:
        conn.execute(
            "UPDATE tenant_owners SET last_login = now() WHERE id = %s",
            (owner_id,),
        )
        conn.commit()
    token = _create_owner_token(owner_id, tenant_id)
    return {"access_token": token, "token_type": "bearer", "tenant_id": tenant_id, "display_name": display_name or ""}


@app.get("/owner/me")
def owner_me(owner: dict = Depends(get_current_owner)):
    """Return current owner profile and tenant info (for dashboard and embed snippet)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT o.id, o.tenant_id, o.email, o.display_name, t.name, t.contact_phone FROM tenant_owners o JOIN tenants t ON t.id = o.tenant_id WHERE o.id = %s",
            (owner["owner_id"],),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Owner not found")
    return {
        "owner_id": row[0],
        "tenant_id": row[1],
        "email": row[2],
        "display_name": row[3] or "",
        "tenant_name": row[4] or row[1],
        "contact_phone": (row[5] or "").strip() if len(row) > 5 else "",
    }


@app.post("/admin/api/create-owner")
def admin_create_owner(body: OwnerCreateBody, authorization: str = Header(default="")):
    """Super admin: create an owner account for a tenant. Protected by ADMIN_TOKEN."""
    _check_admin_auth(authorization)
    email = body.email.strip().lower()
    with get_conn() as conn:
        existing = conn.execute("SELECT 1 FROM tenant_owners WHERE email = %s", (email,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")
        tenant = conn.execute("SELECT 1 FROM tenants WHERE id = %s", (body.tenant_id,)).fetchone()
        if not tenant:
            raise HTTPException(status_code=400, detail="Tenant not found")
        password_hash = _hash_password(body.password)
        conn.execute(
            "INSERT INTO tenant_owners (tenant_id, email, password_hash, display_name) VALUES (%s, %s, %s, %s)",
            (body.tenant_id, email, password_hash, (body.display_name or "").strip() or None),
        )
        conn.commit()
    return {"ok": True, "message": "Owner account created", "tenant_id": body.tenant_id, "email": email}


@app.post("/admin/create-owner")
def admin_create_owner_alias(body: OwnerCreateBody, authorization: str = Header(default="")):
    """Alias for POST /admin/api/create-owner (checklist compatibility)."""
    return admin_create_owner(body, authorization)


def _owner_dashboard_period(period: str = "7d"):
    """Parse period to days and interval for SQL. Returns (days, interval_sql_suffix)."""
    period = (period or "7d").strip().lower()
    if period == "90d":
        return 90, "90 days"
    if period == "30d":
        return 30, "30 days"
    return 7, "7 days"


@app.get("/owner/dashboard")
def owner_dashboard(
    period: str = "7d",
    owner: dict = Depends(get_current_owner),
):
    """Main dashboard stats for the owner's tenant. period=7d|30d|90d."""
    tenant_id = owner["tenant_id"]
    days, interval = _owner_dashboard_period(period)
    with get_conn() as conn:
        # Tenant display name
        row_name = conn.execute(
            "SELECT name FROM tenants WHERE id = %s", (tenant_id,)
        ).fetchone()
        display_name = (row_name[0] if row_name else None) or tenant_id

        # Current period stats from telemetry
        row = conn.execute(
            """
            SELECT
                COUNT(*),
                COUNT(*) FILTER (WHERE date_trunc('day', created_at) = date_trunc('day', now())),
                COUNT(*) FILTER (WHERE debug_branch IN ('fact_miss', 'general_fallback'))
            FROM telemetry
            WHERE tenant_id = %s AND created_at > now() - (%s::text || ' days')::interval
            """,
            (tenant_id, str(days)),
        ).fetchone()
        # For busiest day/hour we need separate aggregates
        busiest = conn.execute(
            """
            SELECT
                EXTRACT(DOW FROM created_at)::integer as dow,
                COUNT(*) as c
            FROM telemetry
            WHERE tenant_id = %s AND created_at > now() - (%s::text || ' days')::interval
            GROUP BY EXTRACT(DOW FROM created_at)
            ORDER BY c DESC LIMIT 1
            """,
            (tenant_id, str(days)),
        ).fetchone()
        busiest_hour_row = conn.execute(
            """
            SELECT EXTRACT(HOUR FROM created_at)::integer as h, COUNT(*) as c
            FROM telemetry
            WHERE tenant_id = %s AND created_at > now() - (%s::text || ' days')::interval
            GROUP BY EXTRACT(HOUR FROM created_at)
            ORDER BY c DESC LIMIT 1
            """,
            (tenant_id, str(days)),
        ).fetchone()
        # Previous period for trend
        prev_row = conn.execute(
            """
            SELECT COUNT(*) FROM telemetry
            WHERE tenant_id = %s
              AND created_at > now() - (%s::text || ' days')::interval * 2
              AND created_at <= now() - (%s::text || ' days')::interval
            """,
            (tenant_id, str(days), str(days)),
        ).fetchone()
    total_queries = row[0] or 0
    queries_today = row[1] or 0
    fallback_count = row[2] or 0
    prev_count = prev_row[0] or 0
    if prev_count and total_queries is not None:
        trend_pct = round((total_queries - prev_count) / prev_count * 100, 1)
        trend = "up" if trend_pct > 0 else "down" if trend_pct < 0 else "flat"
    else:
        trend_pct = 0.0
        trend = "flat"
    day_names = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    busiest_day = day_names[busiest[0]] if busiest else "N/A"
    busiest_hour = int(busiest_hour_row[0]) if busiest_hour_row else 0
    # This week / this month (simple)
    with get_conn() as conn:
        week_row = conn.execute(
            "SELECT COUNT(*) FROM telemetry WHERE tenant_id = %s AND created_at > date_trunc('week', now())",
            (tenant_id,),
        ).fetchone()
        month_row = conn.execute(
            "SELECT COUNT(*) FROM telemetry WHERE tenant_id = %s AND created_at > date_trunc('month', now())",
            (tenant_id,),
        ).fetchone()
    queries_this_week = week_row[0] or 0
    queries_this_month = month_row[0] or 0
    avg_per_day = round(total_queries / days, 1) if days else 0
    return {
        "tenant_id": tenant_id,
        "display_name": display_name,
        "period": f"last_{days}_days",
        "total_queries": total_queries,
        "queries_today": queries_today,
        "queries_this_week": queries_this_week,
        "queries_this_month": queries_this_month,
        "avg_per_day": avg_per_day,
        "busiest_day": busiest_day,
        "busiest_hour": busiest_hour,
        "trend": trend,
        "trend_pct": trend_pct,
        "fallback_count": fallback_count,
    }


@app.get("/owner/dashboard/daily")
def owner_dashboard_daily(
    period: str = "7d",
    owner: dict = Depends(get_current_owner),
):
    """Daily breakdown for charts. Returns [{ date, count }]."""
    tenant_id = owner["tenant_id"]
    days, _ = _owner_dashboard_period(period)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT date_trunc('day', created_at)::date AS d, COUNT(*) AS c
            FROM telemetry
            WHERE tenant_id = %s AND created_at > now() - (%s::text || ' days')::interval
            GROUP BY date_trunc('day', created_at)
            ORDER BY d
            """,
            (tenant_id, str(days)),
        ).fetchall()
    return [{"date": str(r[0]), "count": r[1]} for r in rows]


@app.get("/owner/dashboard/top-questions")
def owner_dashboard_top_questions(
    period: str = "7d",
    owner: dict = Depends(get_current_owner),
):
    """Top query volume patterns (hashes only - no raw text). Returns volume by normalized_hash."""
    tenant_id = owner["tenant_id"]
    days, _ = _owner_dashboard_period(period)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT normalized_hash, COUNT(*) AS c
            FROM telemetry
            WHERE tenant_id = %s AND created_at > now() - (%s::text || ' days')::interval AND normalized_hash IS NOT NULL AND normalized_hash != ''
            GROUP BY normalized_hash
            ORDER BY c DESC
            LIMIT 20
            """,
            (tenant_id, str(days)),
        ).fetchall()
    return [{"query_hash": r[0], "count": r[1]} for r in rows]


@app.get("/owner/dashboard/fallbacks")
def owner_dashboard_fallbacks(
    period: str = "7d",
    owner: dict = Depends(get_current_owner),
):
    """Count of unanswered (fallback) queries in the period."""
    tenant_id = owner["tenant_id"]
    days, _ = _owner_dashboard_period(period)
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM telemetry
            WHERE tenant_id = %s AND created_at > now() - (%s::text || ' days')::interval
              AND debug_branch IN ('fact_miss', 'general_fallback')
            """,
            (tenant_id, str(days)),
        ).fetchone()
    return {"fallback_count": row[0] or 0, "period": f"last_{days}_days"}


# ---------- Owner FAQ self-service (JWT, tenant-scoped) ----------
class OwnerFaqCreate(BaseModel):
    question: str
    answer: str


class OwnerFaqUpdate(BaseModel):
    question: str
    answer: str


def _owner_faq_similarity_warning(tenant_id: str, question_embedding: list, exclude_faq_id: Optional[int] = None) -> Optional[str]:
    """If any live FAQ has cosine similarity > 0.85 with the given embedding, return that FAQ's question text."""
    try:
        with get_conn() as conn:
            exclude = " AND id != %s" if exclude_faq_id is not None else ""
            params = [tenant_id]
            if exclude_faq_id is not None:
                params.append(exclude_faq_id)
            params.extend([question_embedding, question_embedding])
            # pgvector: <=> is cosine distance. 1 - distance = similarity. We want similarity > 0.85 so distance < 0.15
            rows = conn.execute(
                """
                SELECT question FROM faq_items
                WHERE tenant_id = %s AND is_staged = false AND embedding IS NOT NULL
                """ + exclude + """
                AND (embedding <=> %s::vector) < 0.15
                ORDER BY embedding <=> %s::vector
                LIMIT 1
                """,
                params,
            ).fetchall()
            if rows:
                return "This is very similar to your existing question: '" + (rows[0][0] or "") + "' — consider updating that one instead."
    except Exception:
        pass
    return None


def _owner_add_faq_to_live(tenant_id: str, question: str, answer: str) -> tuple:
    """Insert one FAQ as live with variant expansion and embeddings. Returns (faq_id, warning or None)."""
    q = (question or "").strip()
    a = (answer or "").strip()
    if not q or not a:
        raise HTTPException(status_code=400, detail="Question and answer required")
    emb_q = embed_text(q)
    warning = _owner_faq_similarity_warning(tenant_id, emb_q)
    with get_conn() as conn:
        conn.execute("SELECT ensure_faq_variants_partition(%s)", (tenant_id,))
        conn.commit()
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO faq_items (tenant_id, question, answer, embedding, enabled, is_staged) VALUES (%s,%s,%s,%s,true,false) RETURNING id",
            (tenant_id, q, a, Vector(emb_q)),
        ).fetchone()
        faq_id = row[0]
        expanded = expand_faq_list([{"question": q, "answer": a, "variants": []}], max_variants_per_faq=50)
        variants = expanded[0].get("variants", []) if expanded else []
        all_variants = [q] + [v for v in variants if v and v.strip().lower() != q.lower()][:49]
        conn.execute("DELETE FROM faq_variants WHERE faq_id=%s", (faq_id,))
        conn.execute("DELETE FROM faq_variants_p WHERE faq_id=%s AND tenant_id=%s", (faq_id, tenant_id))
        for variant in all_variants[:50]:
            v = (variant or "").strip()
            if not v:
                continue
            try:
                v_emb = embed_text(v)
                conn.execute(
                    "INSERT INTO faq_variants (faq_id, variant_question, variant_embedding, enabled) VALUES (%s,%s,%s,true)",
                    (faq_id, v, Vector(v_emb)),
                )
                conn.execute(
                    "INSERT INTO faq_variants_p (tenant_id, faq_id, variant_question, variant_embedding, enabled) VALUES (%s,%s,%s,%s,true)",
                    (tenant_id, faq_id, v, Vector(v_emb)),
                )
            except Exception:
                continue
        question_variants_text = q + " " + " ".join(all_variants[1:])
        try:
            conn.execute(
                "UPDATE faq_items SET search_vector = setweight(to_tsvector('english', %s), 'A') || setweight(to_tsvector('english', %s), 'C') WHERE id = %s",
                (question_variants_text, a, faq_id),
            )
        except Exception:
            pass
        conn.commit()
    try:
        get_conn().execute("DELETE FROM retrieval_cache WHERE tenant_id = %s", (tenant_id,))
        get_conn().commit()
    except Exception:
        pass
    _invalidate_tenant_count_cache(tenant_id)
    return (faq_id, warning)


def _owner_update_faq_live(tenant_id: str, faq_id: int, question: str, answer: str) -> Optional[str]:
    """Update an existing live FAQ: re-expand variants, re-embed. Returns warning or None."""
    q = (question or "").strip()
    a = (answer or "").strip()
    if not q or not a:
        raise HTTPException(status_code=400, detail="Question and answer required")
    emb_q = embed_text(q)
    warning = _owner_faq_similarity_warning(tenant_id, emb_q, exclude_faq_id=faq_id)
    with get_conn() as conn:
        conn.execute("UPDATE faq_items SET question=%s, answer=%s, embedding=%s, updated_at=now() WHERE id=%s AND tenant_id=%s", (q, a, Vector(emb_q), faq_id, tenant_id))
        if conn.execute("SELECT 1 FROM faq_items WHERE id=%s AND tenant_id=%s", (faq_id, tenant_id)).fetchone() is None:
            raise HTTPException(status_code=404, detail="FAQ not found")
        expanded = expand_faq_list([{"question": q, "answer": a, "variants": []}], max_variants_per_faq=50)
        variants = expanded[0].get("variants", []) if expanded else []
        all_variants = [q] + [v for v in variants if v and v.strip().lower() != q.lower()][:49]
        conn.execute("DELETE FROM faq_variants WHERE faq_id=%s", (faq_id,))
        conn.execute("DELETE FROM faq_variants_p WHERE faq_id=%s AND tenant_id=%s", (faq_id, tenant_id))
        for variant in all_variants[:50]:
            v = (variant or "").strip()
            if not v:
                continue
            try:
                v_emb = embed_text(v)
                conn.execute(
                    "INSERT INTO faq_variants (faq_id, variant_question, variant_embedding, enabled) VALUES (%s,%s,%s,true)",
                    (faq_id, v, Vector(v_emb)),
                )
                conn.execute(
                    "INSERT INTO faq_variants_p (tenant_id, faq_id, variant_question, variant_embedding, enabled) VALUES (%s,%s,%s,%s,true)",
                    (tenant_id, faq_id, v, Vector(v_emb)),
                )
            except Exception:
                continue
        question_variants_text = q + " " + " ".join(all_variants[1:])
        try:
            conn.execute(
                "UPDATE faq_items SET search_vector = setweight(to_tsvector('english', %s), 'A') || setweight(to_tsvector('english', %s), 'C') WHERE id = %s",
                (question_variants_text, a, faq_id),
            )
        except Exception:
            pass
        conn.commit()
    try:
        get_conn().execute("DELETE FROM retrieval_cache WHERE tenant_id = %s", (tenant_id,))
        get_conn().commit()
    except Exception:
        pass
    _invalidate_tenant_count_cache(tenant_id)
    return warning


@app.get("/owner/faqs")
def owner_list_faqs(owner: dict = Depends(get_current_owner)):
    """List all live FAQs for the owner's tenant."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, question, answer FROM faq_items WHERE tenant_id = %s AND is_staged = false ORDER BY id",
            (tenant_id,),
        ).fetchall()
    faqs = [{"id": r[0], "question": r[1], "answer": r[2]} for r in rows]
    return {"faqs": faqs, "count": len(faqs)}


# ---------- Owner FAQ suggestions (suggest only; approve/reject in admin) ----------
class FaqSuggestionCreate(BaseModel):
    question: str
    answer: Optional[str] = None


@app.post("/owner/faqs/suggest")
def owner_suggest_faq(body: FaqSuggestionCreate, owner: dict = Depends(get_current_owner)):
    """Owner suggests a new FAQ. Admin reviews and approves/rejects."""
    tenant_id = owner["tenant_id"]
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question required")
    answer = (body.answer or "").strip() or None
    with get_conn() as conn:
        row = conn.execute(
            """INSERT INTO faq_suggestions (tenant_id, suggested_question, suggested_answer, status)
               VALUES (%s, %s, %s, 'pending') RETURNING id, status""",
            (tenant_id, question, answer),
        ).fetchone()
        conn.commit()
    # Notify Abbed
    with get_conn() as conn:
        email_row = conn.execute(
            "SELECT email FROM tenant_owners WHERE id = %s", (owner["owner_id"],)
        ).fetchone()
    owner_email = (email_row[0] or "").strip() if email_row else ""
    print(f"[FAQ_SUGGESTION] New suggestion from {owner_email} ({tenant_id}): \"{question}\"")
    return {"id": row[0], "status": row[1]}


@app.get("/owner/faqs/suggestions")
def owner_list_suggestions(owner: dict = Depends(get_current_owner)):
    """List all FAQ suggestions for this tenant with their status."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, suggested_question, suggested_answer, status, created_at
               FROM faq_suggestions WHERE tenant_id = %s ORDER BY created_at DESC""",
            (tenant_id,),
        ).fetchall()
    suggestions = [
        {
            "id": r[0],
            "question": r[1],
            "answer": r[2],
            "status": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]
    return {"suggestions": suggestions}


@app.get("/owner/queries")
def owner_queries(
    owner: dict = Depends(get_current_owner),
    days: int = 7,
    limit: int = 50,
    offset: int = 0,
    fallbacks_only: bool = False,
):
    """Query log for owner dashboard. Paginated; optional filter to unanswered only."""
    tenant_id = owner["tenant_id"]
    days = max(1, min(365, days))
    limit = max(1, min(200, limit))
    offset = max(0, offset)
    with get_conn() as conn:
        where = "tenant_id = %s AND created_at > now() - (%s::text || ' days')::interval"
        params = [tenant_id, str(days)]
        if fallbacks_only:
            where += " AND was_fallback = true"
        total_row = conn.execute(
            f"SELECT COUNT(*) FROM query_log WHERE {where}",
            params,
        ).fetchone()
        total = total_row[0] or 0
        rows = conn.execute(
            f"""SELECT id, customer_question, answer_given, matched_faq, was_fallback, created_at
                FROM query_log WHERE {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s""",
            params + [limit, offset],
        ).fetchall()
    queries = [
        {
            "id": r[0],
            "question": (r[1] or "").strip(),
            "answer": (r[2] or "").strip() or None,
            "matched_to": (r[3] or "").strip() or None,
            "answered": not (r[4] or False),
            "timestamp": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]
    return {"queries": queries, "total": total, "period_days": days}


@app.get("/owner/queries/match-counts")
def owner_queries_match_counts(
    owner: dict = Depends(get_current_owner),
    days: int = 7,
):
    """Count of how many times each matched_faq was hit in the period (for 'most asked' badge)."""
    tenant_id = owner["tenant_id"]
    days = max(1, min(365, days))
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT matched_faq, COUNT(*) AS c
               FROM query_log
               WHERE tenant_id = %s AND created_at > now() - (%s::text || ' days')::interval
                 AND matched_faq IS NOT NULL AND TRIM(matched_faq) != ''
               GROUP BY matched_faq""",
            (tenant_id, str(days)),
        ).fetchall()
    return { (r[0] or "").strip(): r[1] for r in rows if (r[0] or "").strip() }


@app.get("/owner/queries/summary")
def owner_queries_summary(owner: dict = Depends(get_current_owner)):
    """Quick summary for stat cards: this_week, today, unanswered, busiest_hour, trend."""
    tenant_id = owner["tenant_id"]
    with get_conn() as conn:
        row = conn.execute(
            """SELECT
                COUNT(*) FILTER (WHERE created_at > now() - interval '7 days'),
                COUNT(*) FILTER (WHERE created_at >= date_trunc('day', now())),
                COUNT(*) FILTER (WHERE created_at > now() - interval '7 days' AND was_fallback = true)
               FROM query_log WHERE tenant_id = %s""",
            (tenant_id,),
        ).fetchone()
        busiest = conn.execute(
            """SELECT EXTRACT(HOUR FROM created_at)::integer
               FROM query_log
               WHERE tenant_id = %s AND created_at > now() - interval '7 days'
               GROUP BY EXTRACT(HOUR FROM created_at)
               ORDER BY COUNT(*) DESC LIMIT 1""",
            (tenant_id,),
        ).fetchone()
        this_week = row[0] or 0
        prev_week = conn.execute(
            """SELECT COUNT(*) FROM query_log
               WHERE tenant_id = %s
                 AND created_at > now() - interval '14 days'
                 AND created_at <= now() - interval '7 days'""",
            (tenant_id,),
        ).fetchone()
        prev_week = prev_week[0] or 0
    trend_pct = None
    if prev_week and this_week is not None:
        if prev_week > 0:
            trend_pct = round(((this_week - prev_week) / prev_week) * 100)
        else:
            trend_pct = 100 if this_week else 0
    hour = int(busiest[0]) if busiest and busiest[0] is not None else None
    if hour is not None:
        if hour == 0:
            busiest_hour = "12am"
        elif hour < 12:
            busiest_hour = f"{hour}am"
        elif hour == 12:
            busiest_hour = "12pm"
        else:
            busiest_hour = f"{hour - 12}pm"
    else:
        busiest_hour = None
    this_week = row[0] or 0
    busiest_insight = None
    if this_week >= 20 and busiest_hour:
        busiest_insight = f"Your busiest time: {busiest_hour} — this is when most customers visit your site."
    return {
        "this_week": this_week,
        "today": row[1] or 0,
        "unanswered_this_week": row[2] or 0,
        "busiest_hour": busiest_hour,
        "trend_vs_last_week": f"{'+' if trend_pct and trend_pct >= 0 else ''}{trend_pct}%" if trend_pct is not None else None,
        "busiest_insight": busiest_insight,
    }


@app.get("/owner/queries/daily")
def owner_queries_daily(
    owner: dict = Depends(get_current_owner),
    period: str = "7d",
):
    """Daily query counts from query_log for chart. period=7d|30d|90d."""
    tenant_id = owner["tenant_id"]
    days, _ = _owner_dashboard_period(period)
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT date_trunc('day', created_at)::date AS d, COUNT(*) AS c
               FROM query_log
               WHERE tenant_id = %s AND created_at > now() - (%s::text || ' days')::interval
               GROUP BY date_trunc('day', created_at)
               ORDER BY d""",
            (tenant_id, str(days)),
        ).fetchall()
    return [{"date": str(r[0]), "count": r[1]} for r in rows]


@app.get("/owner/queries/export")
def owner_queries_export(
    owner: dict = Depends(get_current_owner),
    days: int = 30,
):
    """Export query log as CSV. JWT protected."""
    tenant_id = owner["tenant_id"]
    days = max(1, min(365, days))
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT created_at, customer_question, answer_given, matched_faq, was_fallback
               FROM query_log
               WHERE tenant_id = %s AND created_at > now() - (%s::text || ' days')::interval
               ORDER BY created_at DESC""",
            (tenant_id, str(days)),
        ).fetchall()
    import io
    import csv
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["timestamp", "question", "answer", "matched_to", "answered"])
    for r in rows:
        w.writerow([
            r[0].strftime("%Y-%m-%d %H:%M:%S") if r[0] else "",
            (r[1] or "").strip(),
            (r[2] or "").strip() or "",
            (r[3] or "").strip() or "",
            "yes" if not (r[4] or False) else "no",
        ])
    response = Response(content=buf.getvalue(), media_type="text/csv")
    response.headers["Content-Disposition"] = f'attachment; filename="queries_{tenant_id}_{days}d.csv"'
    return response


@app.get("/admin/weekly-summary-log")
def admin_weekly_summary_log(authorization: str = Header(default="")):
    """Log weekly query summary per tenant. Call from cron (e.g. Monday 9am AEST).
    # TODO: Send actual email summaries to owners."""
    _check_admin_auth(authorization)
    with get_conn() as conn:
        tenants = conn.execute(
            "SELECT id FROM tenants ORDER BY id",
            (),
        ).fetchall()
    for (tid,) in tenants:
        tid = tid or ""
        with get_conn() as conn:
            row = conn.execute(
                """SELECT
                    COUNT(*) FILTER (WHERE created_at > now() - interval '7 days'),
                    COUNT(*) FILTER (WHERE created_at > now() - interval '14 days' AND created_at <= now() - interval '7 days'),
                    COUNT(*) FILTER (WHERE created_at > now() - interval '7 days' AND was_fallback = true)
                   FROM query_log WHERE tenant_id = %s""",
                (tid,),
            ).fetchone()
        this_week = row[0] or 0
        prev_week = row[1] or 0
        unanswered = row[2] or 0
        trend = ""
        if prev_week and this_week is not None:
            pct = round(((this_week - prev_week) / prev_week) * 100)
            trend = f"{'+' if pct >= 0 else ''}{pct}%"
        print(f"[WEEKLY_SUMMARY] {tid}: {this_week} questions this week ({trend}), {unanswered} unanswered")
    return {"ok": True}


class GenerateFaqsFromUrlBody(BaseModel):
    url: str
    business_type: str = "other"
    business_name: str = ""


def _generate_faqs_from_url(
    url: str,
    business_name: str,
    business_type: str = "other",
) -> List[dict]:
    """Scrape URL, extract text, use LLM to suggest 8-12 FAQs. Returns list of {question, answer}. Raises HTTPException on failure."""
    url = (url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    business_type = (business_type or "other").strip() or "other"
    business_name = (business_name or "").strip() or "this business"
    try:
        import requests as req_lib
        resp = req_lib.get(url, timeout=10, headers={"User-Agent": "MotionMade FAQ Builder"})
        resp.raise_for_status()
        html_content = resp.text
    except Exception:
        raise HTTPException(status_code=400, detail="Couldn't access that website. Check the URL and try again.")
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        website_text = (text or "")[:4000]
    except Exception:
        raise HTTPException(status_code=400, detail="Couldn't extract text from that website. Try again.")
    system_prompt = f'''You are a FAQ generator for small service businesses.
Given website content from a {business_type} business called "{business_name}",
generate 8-12 frequently asked questions that customers would ask.

Rules:
- Questions should be from the CUSTOMER's perspective ("How much...", "Do you...", "What areas...")
- Answers should use specific details from the website (prices, areas, services, phone numbers)
- If the website doesn't have specific info (like prices), write the answer with a placeholder like "[PRICE]" that the admin can fill in
- Keep answers concise (1-3 sentences)
- Include questions about: pricing, areas/coverage, booking process, what's included, payment methods, guarantees, insurance/licensing
- Write in a natural, friendly Australian tone

Return ONLY a JSON array of objects: [{{"question": "...", "answer": "..."}}]
No other text, no markdown, no explanation.'''
    user_prompt = f"Website content from {business_name} ({url}):\n\n{website_text}"
    try:
        raw = chat_once(
            system_prompt,
            user_prompt,
            temperature=0.3,
            max_tokens=2000,
            timeout=15,
            model="gpt-4o-mini",
        )
    except Exception:
        raise HTTPException(status_code=500, detail="Couldn't generate FAQs from that site. Try adding some manually.")
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        suggested = json.loads(raw)
    except json.JSONDecodeError:
        try:
            raw2 = chat_once(
                system_prompt,
                user_prompt,
                temperature=0.2,
                max_tokens=2000,
                timeout=15,
                model="gpt-4o-mini",
            )
            raw2 = (raw2 or "").strip()
            if raw2.startswith("```"):
                raw2 = re.sub(r"^```(?:json)?\s*", "", raw2)
                raw2 = re.sub(r"\s*```$", "", raw2)
            suggested = json.loads(raw2)
        except (json.JSONDecodeError, Exception):
            raise HTTPException(status_code=500, detail="Couldn't generate FAQs from that site. Try adding some manually.")
    if not isinstance(suggested, list):
        raise HTTPException(status_code=500, detail="Couldn't generate FAQs from that site. Try adding some manually.")
    faqs = []
    for item in suggested[:20]:
        if isinstance(item, dict) and item.get("question"):
            faqs.append({
                "question": str(item.get("question", "")).strip(),
                "answer": str(item.get("answer", "")).strip() or "",
            })
    return faqs


@app.post("/admin/api/generate-faqs-from-url")
def admin_generate_faqs_from_url(
    body: GenerateFaqsFromUrlBody,
    authorization: str = Header(default=""),
):
    """Fetch a website, extract text, and use GPT to suggest 8-12 FAQs. ADMIN_TOKEN protected."""
    _check_admin_auth(authorization)
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    business_type = (body.business_type or "other").strip() or "other"
    business_name = (body.business_name or "").strip() or "this business"
    try:
        faqs = _generate_faqs_from_url(url, business_name, business_type)
    except HTTPException as e:
        return {"error": (e.detail if isinstance(e.detail, str) else str(e.detail))}
    return {
        "business_name": business_name,
        "url": url,
        "suggested_faqs": faqs,
        "source": "website_scrape",
    }


# ---------- Demo widget: generate + public preview (no auth) ----------
DEMO_EXPIRY_DAYS = 14


class DemoGenerateBody(BaseModel):
    business_url: str
    business_name: str


def _create_demo_internal(business_name: str, business_url: str) -> dict:
    """Create a demo widget: scrape URL, generate FAQs, create tenant, stage, promote in-process, store demo. Returns {demo_id, preview_url, faq_count}. Raises HTTPException on failure. Call this directly to avoid self-HTTP deadlock on single-worker."""
    import secrets

    url = (business_url or "").strip()
    name = (business_name or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="business_url required")
    if not name:
        raise HTTPException(status_code=400, detail="business_name required")
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    faqs = _generate_faqs_from_url(url, name, business_type="other")
    if not faqs:
        raise HTTPException(status_code=400, detail="No FAQs could be generated from that URL.")

    short_id = secrets.token_urlsafe(6)
    tenant_id = "demo_" + short_id

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO tenants (id, name, business_type, contact_phone)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name""",
            (tenant_id, name, "other", None),
        )
        conn.commit()

    _stage_faqs_internal(tenant_id, faqs)

    # Promote in-process (no HTTP) to avoid deadlock on single-worker
    try:
        promote_staged(tenant_id, Response(), f"Bearer {settings.ADMIN_TOKEN}")
    except Exception as e:
        with get_conn() as conn:
            conn.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))
            conn.commit()
        raise HTTPException(status_code=500, detail=f"Demo created but promotion failed: {str(e)}")

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO demos (slug, tenant_id, business_name, business_url) VALUES (%s, %s, %s, %s)""",
            (short_id, tenant_id, name, url),
        )
        conn.commit()

    base_url = os.getenv("PUBLIC_BASE_URL") or (
        "http://127.0.0.1:8000" if not os.getenv("RENDER") else "https://motionmade-fastapi.onrender.com"
    )
    preview_url = f"{base_url}/demo/{short_id}"
    return {"demo_id": short_id, "preview_url": preview_url, "faq_count": len(faqs)}


@app.post("/api/demo/generate")
def demo_generate(body: DemoGenerateBody):
    """Generate a demo widget for a business. Public (no auth)."""
    return _create_demo_internal(body.business_name, body.business_url)


@app.get("/demo/{slug}", response_class=HTMLResponse)
def demo_preview_page(slug: str):
    """Public preview page: show business name, embedded widget (demo FAQs), and CTA. Expired demos show a friendly message."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT slug, tenant_id, business_name, business_url, created_at FROM demos WHERE slug = %s",
            (slug.strip(),),
        ).fetchone()

    if not row:
        return _render_demo_expired_html()

    _, tenant_id, business_name, business_url, created_at = row
    if created_at:
        from datetime import timezone
        now = datetime.now(timezone.utc)
        created_utc = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        if (now - created_utc).days >= DEMO_EXPIRY_DAYS:
            return _render_demo_expired_html()

    base_url = os.getenv("PUBLIC_BASE_URL") or (
        "http://127.0.0.1:8000" if not os.getenv("RENDER") else "https://motionmade-fastapi.onrender.com"
    )
    html_path = Path(__file__).resolve().parent / "templates" / "demo.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Demo template not found</h1>", status_code=500)
    html = html_path.read_text(encoding="utf-8")
    html = html.replace("__BUSINESS_NAME__", _escape_html(business_name or "This business"))
    html = html.replace("__TENANT_ID__", _escape_html(tenant_id))
    html = html.replace("__BASE_URL__", _escape_html(base_url.rstrip("/")))
    return HTMLResponse(content=html)


def _escape_html(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _render_demo_expired_html() -> HTMLResponse:
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Demo expired – MotionMade</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'DM Sans', sans-serif; background: #f0f3f8; color: #0b1222; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }
        .card { background: #fff; border-radius: 12px; padding: 48px; max-width: 420px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,.08); }
        h1 { font-size: 22px; font-weight: 600; margin-bottom: 12px; }
        p { color: #6b7a94; font-size: 16px; line-height: 1.5; margin-bottom: 24px; }
        a { color: #2563eb; text-decoration: none; font-weight: 500; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="card">
        <h1>This demo has expired</h1>
        <p>Demo previews are available for 14 days. Want a live widget for your business?</p>
        <a href="https://motionmade.com.au">Get started at motionmade.com.au</a>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


# ---------- Outreach: SendGrid + rate limits (admin-only) ----------
OUTREACH_RATE_LIMIT_PER_HOUR = 20
OUTREACH_RATE_LIMIT_PER_DAY = 50


class OutreachSendBody(BaseModel):
    to_email: str
    subject: str
    body: str
    from_name: str = "Abbed"
    reply_to: str = "abbed@motionmadebne.com.au"
    lead_name: Optional[str] = None


@app.post("/api/outreach/send")
def outreach_send(
    body: OutreachSendBody,
    authorization: str = Header(default=""),
):
    """Send a single plain-text email via SendGrid. Logged in outreach_log. Rate limited: 20/hour, 50/day. Admin-only."""
    _check_admin_auth(authorization)

    to_email = (body.to_email or "").strip()
    subject = (body.subject or "").strip()
    body_text = (body.body or "").strip()
    if not to_email:
        raise HTTPException(status_code=400, detail="to_email required")
    if not subject:
        raise HTTPException(status_code=400, detail="subject required")

    with get_conn() as conn:
        hour_ago = conn.execute(
            "SELECT COUNT(*) FROM outreach_log WHERE sent_at > now() - interval '1 hour'"
        ).fetchone()[0]
        day_ago = conn.execute(
            "SELECT COUNT(*) FROM outreach_log WHERE sent_at > now() - interval '24 hours'"
        ).fetchone()[0]
    if hour_ago >= OUTREACH_RATE_LIMIT_PER_HOUR:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {OUTREACH_RATE_LIMIT_PER_HOUR} emails per hour. Try again later.",
        )
    if day_ago >= OUTREACH_RATE_LIMIT_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: max {OUTREACH_RATE_LIMIT_PER_DAY} emails per day. Try again tomorrow.",
        )

    from_email = os.getenv("OUTREACH_FROM_EMAIL", "").strip()
    api_key = os.getenv("SENDGRID_API_KEY", "").strip()
    if not from_email or not api_key:
        raise HTTPException(
            status_code=500,
            detail="Outreach not configured: set OUTREACH_FROM_EMAIL and SENDGRID_API_KEY.",
        )

    status = "failed"
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To, Content, ReplyTo

        message = Mail(
            from_email=Email(from_email, (body.from_name or "Abbed").strip()),
            to_emails=To(to_email),
            subject=subject,
            plain_text_content=Content("text/plain", body_text),
        )
        reply_to_addr = (body.reply_to or "").strip()
        if reply_to_addr:
            message.reply_to = ReplyTo(reply_to_addr)
        sg = SendGridAPIClient(api_key)
        sg.send(message)
        status = "sent"
    except Exception as e:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO outreach_log (to_email, subject, body, status, lead_name)
                   VALUES (%s, %s, %s, %s, %s)""",
                (to_email, subject, body_text, "failed", (body.lead_name or "").strip() or None),
            )
            conn.commit()
        raise HTTPException(status_code=500, detail=f"SendGrid error: {str(e)}")

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO outreach_log (to_email, subject, body, status, lead_name)
               VALUES (%s, %s, %s, %s, %s)""",
            (to_email, subject, body_text, status, (body.lead_name or "").strip() or None),
        )
        conn.commit()

    return {"ok": True, "status": status, "to_email": to_email}


@app.get("/admin/api/contact-submissions")
def admin_contact_submissions(authorization: str = Header(default="")):
    """View all contact form submissions from the landing page. Admin-only."""
    _check_admin_auth(authorization)
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, name, business, email, phone, business_type, message, created_at
               FROM contact_submissions ORDER BY created_at DESC LIMIT 50"""
        ).fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "business": r[2],
            "email": r[3],
            "phone": r[4],
            "type": r[5],
            "message": r[6],
            "submitted": r[7].isoformat() if r[7] else None,
        }
        for r in rows
    ]


# ---------- Leads engine (admin-only internal tool) ----------
LEADS_STATUSES = ["new", "audited", "previewed", "ready", "emailed", "replied", "converted", "skip"]
BRISBANE_SUBURBS = [
    "Acacia Ridge", "Albion", "Alderley", "Annerley", "Ascot", "Ashgrove", "Aspley", "Auchenflower",
    "Bald Hills", "Balmoral", "Banyo", "Bardon", "Belmont", "Boondall", "Bowen Hills", "Bracken Ridge",
    "Bridgeman Downs", "Brighton", "Brisbane City", "Bulimba", "Calamvale", "Camp Hill", "Cannon Hill",
    "Carina", "Carindale", "Carole Park", "Chandler", "Chapel Hill", "Chelmer", "Chermside", "Chermside West",
    "Clayfield", "Coorparoo", "Corinda", "Deagon", "Durack", "Eagle Farm", "East Brisbane", "Ellen Grove",
    "Enoggera", "Everton Park", "Fairfield", "Ferny Grove", "Ferny Hills", "Fig Tree Pocket", "Fortitude Valley",
    "Gaythorne", "Geebung", "Gordon Park", "Graceville", "Grange", "Greenslopes", "Gumdale", "Hamilton",
    "Hawthorne", "Heathwood", "Holland Park", "Holland Park West", "Inala", "Indooroopilly", "Jamboree Heights",
    "Jindalee", "Kalinga", "Kangaroo Point", "Kedron", "Kelvin Grove", "Kenmore", "Kenmore Hills", "Keperra",
    "Kuraby", "Lutwyche", "Lytton", "Macgregor", "McDowall", "Manly", "Manly West", "Mansfield", "Middle Park",
    "Milton", "Mitchelton", "Moggill", "Mount Gravatt", "Mount Ommaney", "Murarrie", "Nathan", "New Farm",
    "Newmarket", "Norman Park", "Northgate", "Nudgee", "Nundah", "Oxley", "Paddington", "Pallara",
    "Parkinson", "Petrie Terrace", "Pinjarra Hills", "Pullenvale", "Ransome", "Red Hill", "Richlands",
    "Rochedale", "Rocklea", "Runcorn", "Salisbury", "Sandgate", "Seven Hills", "Sherwood", "Shorncliffe",
    "Sinnamon Park", "South Brisbane", "Spring Hill", "St Lucia", "Stafford", "Stafford Heights", "Stones Corner",
    "Stretton", "Sumner", "Sunnybank", "Sunnybank Hills", "Taigum", "Taringa", "Tarragindi", "Teneriffe",
    "The Gap", "Toowong", "Upper Mount Gravatt", "Virginia", "Wavell Heights", "West End", "Wilston",
    "Windsor", "Wishart", "Woolloongabba", "Wooloowin", "Wynnum", "Wynnum West", "Yeronga", "Zillmere",
]
GOLD_COAST_SUBURBS = [
    "Broadbeach", "Burleigh Heads", "Coolangatta", "Currumbin", "Main Beach", "Mermaid Beach", "Nobby Beach",
    "Palm Beach", "Surfers Paradise", "Southport", "Robina", "Varsity Lakes", "Carrara", "Coomera", "Helensvale",
    "Hope Island", "Labrador", "Miami", "Ormeau", "Oxenford", "Pacific Pines", "Paradise Point", "Runaway Bay",
    "Tallai", "Tugun", "Upper Coomera", "Worongary",
]
SUNSHINE_COAST_SUBURBS = [
    "Alexandra Headland", "Buderim", "Caloundra", "Coolum Beach", "Kawana Waters", "Maroochydore", "Mooloolaba",
    "Noosa Heads", "Noosaville", "Nambour", "Peregian Springs", "Sippy Downs", "Sunshine Beach", "Tewantin",
    "Bli Bli", "Bokarina", "Eumundi", "Golden Beach", "Kings Beach", "Maleny", "Marcoola", "Mountain Creek",
    "Palmwoods", "Pelican Waters", "Warana", "Wurtulla", "Yandina",
]
SYDNEY_SUBURBS = [
    "Bondi", "Bondi Junction", "Chatswood", "Manly", "North Sydney", "Parramatta", "Surry Hills", "Sydney CBD",
    "Darlinghurst", "Newtown", "Marrickville", "Randwick", "Coogee", "Bronte", "Paddington", "Mosman",
    "Neutral Bay", "Cremorne", "Lane Cove", "Ryde", "Burwood", "Strathfield", "Ashfield", "Leichhardt",
    "Balmain", "Drummoyne", "Five Dock", "Concord", "Hurstville", "Kogarah", "Rockdale", "Cronulla",
]
MELBOURNE_SUBURBS = [
    "Carlton", "Collingwood", "Fitzroy", "Richmond", "South Yarra", "St Kilda", "Prahran", "Melbourne CBD",
    "Brunswick", "Northcote", "Thornbury", "Preston", "Hawthorn", "Camberwell", "Kew", "Malvern",
    "Brighton", "Elwood", "Port Melbourne", "South Melbourne", "Footscray", "Yarraville", "Williamstown",
    "Box Hill", "Doncaster", "Templestowe", "Glen Waverley", "Clayton", "Bentleigh", "Caulfield", "Oakleigh",
]
PERTH_SUBURBS = [
    "Northbridge", "Subiaco", "Leederville", "Mount Lawley", "East Perth", "West Perth", "Perth CBD",
    "Fremantle", "South Perth", "Victoria Park", "Como", "Applecross", "Cottesloe", "Scarborough",
    "Joondalup", "Hillarys", "Whitfords", "Sorrento", "Greenwood", "Kingsley", "Woodvale", "Currambine",
    "Mandurah", "Rockingham", "Baldivis", "Canning Vale", "Willetton", "Thornlie", "Gosnells", "Armadale",
]
CITIES = ["Brisbane", "Gold Coast", "Sunshine Coast", "Sydney", "Melbourne", "Perth"]
CITY_SUBURBS = {
    "Brisbane": BRISBANE_SUBURBS,
    "Gold Coast": GOLD_COAST_SUBURBS,
    "Sunshine Coast": SUNSHINE_COAST_SUBURBS,
    "Sydney": SYDNEY_SUBURBS,
    "Melbourne": MELBOURNE_SUBURBS,
    "Perth": PERTH_SUBURBS,
}


def _autopilot_log(phase: str, message: str, detail: Optional[dict] = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO autopilot_log (phase, message, detail) VALUES (%s, %s, %s)",
            (phase, message, json.dumps(detail) if detail else None),
        )
        conn.commit()


def _llm_retry(phase: str, fn, max_retries: int = 3):
    """Run an LLM API call (OpenAI) with retry on 429. Up to max_retries retries (4 attempts total)."""
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            err_repr = repr(e)
            is_429 = getattr(e, "status_code", None) == 429
            if not is_429:
                try:
                    import openai
                    is_429 = isinstance(e, getattr(openai, "RateLimitError", type(None)))
                except Exception:
                    pass
            if not is_429:
                is_429 = "429" in err_repr or "429" in str(e) or "rate_limit" in err_str or "rate limit" in err_str
            _autopilot_log(phase, f"LLM exception type: {type(e).__name__}", {"repr": err_repr[:500], "is_429": is_429})
            if is_429 and attempt < max_retries:
                _autopilot_log(phase, "Rate limited. Waiting 60 seconds...", {})
                time.sleep(60)
                continue
            raise
    if last_err is not None:
        raise last_err


@app.get("/leads", response_class=HTMLResponse)
def leads_ui():
    """Serve leads engine UI. Auth is via admin token in the page (same as /admin)."""
    html_path = Path(__file__).resolve().parent / "templates" / "leads.html"
    if not html_path.exists():
        return HTMLResponse(content="<h1>Leads page not found</h1>", status_code=404)
    html = html_path.read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/api/leads")
def api_leads_list(
    trade_type: Optional[str] = None,
    suburb: Optional[str] = None,
    status: Optional[str] = None,
    authorization: str = Header(default=""),
):
    """List leads with optional filters. Admin-only."""
    _check_admin_auth(authorization)
    with get_conn() as conn:
        q = "SELECT id, trade_type, suburb, business_name, website, email, status, audit_score, audit_details, preview_url, preview_demo_id, email_subject, email_body, created_at, updated_at FROM leads WHERE 1=1"
        params: list = []
        if trade_type:
            q += " AND trade_type = %s"
            params.append(trade_type)
        suburb_val = (suburb or "").strip()
        if suburb_val and suburb_val.lower() != "all":
            q += " AND suburb = %s"
            params.append(suburb_val)
        if status:
            q += " AND status = %s"
            params.append(status)
        q += " ORDER BY created_at DESC"
        rows = conn.execute(q, tuple(params)).fetchall()
    leads = []
    for r in rows:
        leads.append({
            "id": r[0],
            "trade_type": r[1],
            "suburb": r[2],
            "business_name": r[3],
            "website": r[4],
            "email": r[5],
            "status": r[6],
            "audit_score": r[7],
            "audit_details": r[8],
            "preview_url": r[9],
            "preview_demo_id": r[10],
            "email_subject": r[11],
            "email_body": r[12],
            "created_at": r[13].isoformat() if r[13] else None,
            "updated_at": r[14].isoformat() if r[14] else None,
        })
    return {"leads": leads}


@app.get("/api/leads/cities")
def api_leads_cities(authorization: str = Header(default="")):
    """Return list of cities for region selector. Admin-only."""
    _check_admin_auth(authorization)
    return {"cities": CITIES}


@app.get("/api/leads/suburbs")
def api_leads_suburbs(
    city: Optional[str] = None,
    authorization: str = Header(default=""),
):
    """Return suburbs for the given city. Admin-only. Default city Brisbane."""
    _check_admin_auth(authorization)
    key = (city or "").strip() or "Brisbane"
    return {"suburbs": CITY_SUBURBS.get(key, BRISBANE_SUBURBS)}


def _daily_email_limit() -> int:
    """Daily email limit from env (default 20)."""
    try:
        return max(1, int(os.getenv("DAILY_EMAIL_LIMIT", "20").strip()))
    except ValueError:
        return 20


@app.get("/api/leads/daily-sent-count")
def api_leads_daily_sent_count(authorization: str = Header(default="")):
    """Count leads marked as emailed today (AEST) and daily limit. Admin-only."""
    _check_admin_auth(authorization)
    limit = _daily_email_limit()
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) FROM leads
               WHERE status = 'emailed'
               AND (updated_at AT TIME ZONE 'Australia/Brisbane')::date = (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Brisbane')::date"""
        ).fetchone()
    count = row[0] if row else 0
    return {"count": count, "limit": limit}


@app.get("/api/leads/autopilot/log")
def api_autopilot_log(
    since_id: Optional[int] = None,
    limit: int = 100,
    authorization: str = Header(default=""),
):
    """Return recent autopilot log entries for live log. Admin-only."""
    _check_admin_auth(authorization)
    with get_conn() as conn:
        if since_id:
            rows = conn.execute(
                "SELECT id, phase, message, detail, created_at FROM autopilot_log WHERE id > %s ORDER BY id ASC LIMIT %s",
                (since_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, phase, message, detail, created_at FROM autopilot_log ORDER BY id DESC LIMIT %s",
                (limit,),
            ).fetchall()
            rows = list(reversed(rows))
    entries = [{"id": r[0], "phase": r[1], "message": r[2], "detail": r[3], "created_at": r[4].isoformat() if r[4] else None} for r in rows]
    return {"log": entries}


@app.post("/api/leads/autopilot/clear-log")
def api_leads_autopilot_clear_log(authorization: str = Header(default="")):
    """Delete all autopilot log entries. Admin-only."""
    _check_admin_auth(authorization)
    with get_conn() as conn:
        conn.execute("DELETE FROM autopilot_log")
        conn.commit()
    return {"ok": True}


@app.get("/api/leads/export")
def api_leads_export(
    trade_type: Optional[str] = None,
    suburb: Optional[str] = None,
    authorization: str = Header(default=""),
):
    """CSV export of ready leads only: Business Name, Email Address, Email Subject, Email Body, Website, Trade Type, Suburb, Audit Score. Admin-only."""
    _check_admin_auth(authorization)
    with get_conn() as conn:
        q = "SELECT business_name, email, email_subject, email_body, website, trade_type, suburb, audit_score FROM leads WHERE status = 'ready'"
        params: list = []
        if trade_type:
            q += " AND trade_type = %s"
            params.append(trade_type)
        if suburb:
            q += " AND suburb = %s"
            params.append(suburb)
        q += " ORDER BY business_name"
        rows = conn.execute(q, tuple(params)).fetchall()

    import io
    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Business Name", "Email Address", "Email Subject", "Email Body", "Website", "Trade Type", "Suburb", "Audit Score"])
    for r in rows:
        writer.writerow([
            r[0] or "",
            r[1] or "",
            (r[2] or "").replace("\r", "").replace("\n", " "),
            (r[3] or "").replace("\r", " ").replace("\n", " "),
            r[4] or "",
            r[5] or "",
            r[6] or "",
            r[7] if r[7] is not None else "",
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads_export.csv"},
    )


@app.get("/api/leads/{lead_id}")
def api_lead_get(
    lead_id: int,
    authorization: str = Header(default=""),
):
    """Get a single lead by id. Admin-only."""
    _check_admin_auth(authorization)
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, trade_type, suburb, business_name, website, email, status, audit_score, audit_details, preview_url, preview_demo_id, email_subject, email_body, created_at, updated_at FROM leads WHERE id = %s",
            (lead_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {
        "id": row[0], "trade_type": row[1], "suburb": row[2], "business_name": row[3], "website": row[4],
        "email": row[5], "status": row[6], "audit_score": row[7], "audit_details": row[8], "preview_url": row[9],
        "preview_demo_id": row[10], "email_subject": row[11], "email_body": row[12],
        "created_at": row[13].isoformat() if row[13] else None, "updated_at": row[14].isoformat() if row[14] else None,
    }


@app.patch("/api/leads/{lead_id}")
def api_leads_update(
    lead_id: int,
    body: dict,
    authorization: str = Header(default=""),
):
    """Update a lead (status, email, etc.). Admin-only."""
    _check_admin_auth(authorization)
    allowed = {"status", "email", "email_subject", "email_body", "business_name", "website", "audit_score", "audit_details", "preview_url", "preview_demo_id"}
    updates = {k: v for k, v in (body or {}).items() if k in allowed}
    if not updates:
        return {"ok": True}
    sets = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [lead_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE leads SET {sets}, updated_at = now() WHERE id = %s", tuple(values))
        conn.commit()
    return {"ok": True}


@app.post("/api/leads/mark-ready-as-emailed")
def api_leads_mark_ready_as_emailed(
    trade_type: Optional[str] = None,
    suburb: Optional[str] = None,
    authorization: str = Header(default=""),
):
    """Set all leads with status 'ready' to 'emailed'. Optional trade_type/suburb filter. Admin-only."""
    _check_admin_auth(authorization)
    with get_conn() as conn:
        q = "UPDATE leads SET status = 'emailed', updated_at = now() WHERE status = 'ready'"
        params: list = []
        if trade_type:
            q += " AND trade_type = %s"
            params.append(trade_type)
        if suburb:
            q += " AND suburb = %s"
            params.append(suburb)
        conn.execute(q, tuple(params))
        conn.commit()
    return {"ok": True}


class AutopilotDiscoveryBody(BaseModel):
    trade_type: str
    suburb: str
    city: str = "Brisbane"
    target_count: int = 20


@app.post("/api/leads/autopilot/discovery")
def api_autopilot_discovery(
    body: AutopilotDiscoveryBody,
    authorization: str = Header(default=""),
):
    """Run discovery: use OpenAI GPT-4o to generate realistic local business leads for the trade/location. Admin-only."""
    _check_admin_auth(authorization)
    try:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")

        trade = (body.trade_type or "").strip() or "Plumber"
        suburb = (body.suburb or "").strip() or ""
        city = (body.city or "").strip() or "Brisbane"
        suburb_area = f" in {suburb}" if suburb else f" in {city} area"
        target = max(10, min(50, body.target_count or 20))

        with get_conn() as conn_log:
            conn_log.execute("DELETE FROM autopilot_log")
            conn_log.commit()
        _autopilot_log("discovery", f"Starting discovery: {trade}{suburb_area}, target {target}")

        import openai
        client = openai.OpenAI(api_key=api_key)

        location = f"{suburb}, {city}" if suburb else city
        prompt = f"""Based on your knowledge of local businesses in {location}, Australia, generate a list of realistic local businesses for the trade: {trade}.

These can be real businesses you know of from your training data, or plausible local business names and domains for this area. Local service businesses (plumbers, cleaners, etc.) in Australian suburbs are well established and well indexed.

For each business provide:
- business_name (string): plausible business name
- website (URL if known or plausible, else null)
- email (email if known or use a plausible pattern like info@businessname.com.au, else null)

Return a JSON array of objects with keys: business_name, website, email. Include up to {min(target, 30)} businesses. No other text, no markdown, only the JSON array."""

        resp = _llm_retry("discovery", lambda: client.chat.completions.create(
            model="gpt-4o",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        ))
        text = (resp.choices[0].message.content or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            businesses = json.loads(text)
        except json.JSONDecodeError:
            _autopilot_log("discovery", "Could not parse discovery response as JSON", {"raw": text[:500]})
            raise HTTPException(status_code=500, detail="Discovery returned invalid JSON")

        if not isinstance(businesses, list):
            businesses = []

        from urllib.parse import urlparse

        def _normalise_domain(url: Optional[str]) -> Optional[str]:
            if not url or not url.strip():
                return None
            u = (url or "").strip().lower()
            if not u.startswith(("http://", "https://")):
                u = "https://" + u
            try:
                netloc = urlparse(u).netloc or ""
                if netloc.startswith("www."):
                    netloc = netloc[4:]
                return netloc.strip("/") or None
            except Exception:
                return None

        inserted = 0
        with get_conn() as conn:
            existing_domains: Set[str] = set()
            for row in conn.execute("SELECT website FROM leads WHERE website IS NOT NULL AND website != ''").fetchall():
                d = _normalise_domain(row[0])
                if d:
                    existing_domains.add(d)
            for b in businesses[:target]:
                name = (b.get("business_name") or "").strip()
                if not name:
                    continue
                website = (b.get("website") or "").strip() or None
                email = (b.get("email") or "").strip() or None
                if not website and not email:
                    continue
                existing = conn.execute(
                    "SELECT 1 FROM leads WHERE LOWER(TRIM(business_name)) = LOWER(%s) LIMIT 1",
                    (name,),
                ).fetchone()
                if existing:
                    continue
                domain = _normalise_domain(website)
                if domain and domain in existing_domains:
                    continue
                conn.execute(
                    """INSERT INTO leads (trade_type, suburb, business_name, website, email, status)
                       VALUES (%s, %s, %s, %s, %s, 'new')""",
                    (trade, (suburb or "").strip() or city or "Brisbane", name, website, email),
                )
                conn.commit()
                inserted += 1
                if domain:
                    existing_domains.add(domain)

        _autopilot_log("discovery", f"Inserted {inserted} new leads", {"count": inserted})
        return {"ok": True, "inserted": inserted, "total_found": len(businesses)}
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[DISCOVERY] {tb}")
        _autopilot_log("discovery", str(e), {"traceback": tb})
        raise HTTPException(status_code=500, detail=f"Discovery failed:\n{tb}")


# Leads table has no unique constraint; we avoid duplicate by checking (trade_type, suburb, business_name) if needed later.


class AutopilotAuditBody(BaseModel):
    lead_ids: Optional[List[int]] = None  # None = all with status new


@app.post("/api/leads/autopilot/audit")
def api_autopilot_audit(
    body: AutopilotAuditBody,
    authorization: str = Header(default=""),
):
    """Audit leads: fetch website with requests/BeautifulSoup, use OpenAI GPT-4o to score 1-10 and check for chat/FAQ/after-hours. Only processes status='new' (never re-audits ready/emailed). Admin-only."""
    _check_admin_auth(authorization)
    try:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")

        with get_conn() as conn:
            if body.lead_ids:
                placeholders = ",".join(["%s"] * len(body.lead_ids))
                rows = conn.execute(
                    f"SELECT id, business_name, website, email, suburb FROM leads WHERE id IN ({placeholders})",
                    tuple(body.lead_ids),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, business_name, website, email, suburb FROM leads WHERE status = 'new' AND website IS NOT NULL AND website != ''"
                ).fetchall()

        import openai
        from urllib.parse import urljoin, urlparse
        client = openai.OpenAI(api_key=api_key)
        _email_re = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

        def _collect_emails_from_page(soup, raw_html: str) -> list[str]:
            candidates: list[str] = []
            for a in soup.find_all("a", href=True):
                h = (a.get("href") or "").strip()
                if h.lower().startswith("mailto:"):
                    addr = h[7:].split("?")[0].strip().strip("/")
                    if addr and "@" in addr:
                        candidates.append(addr)
            for m in _email_re.finditer(raw_html):
                candidates.append(m.group(0))
            seen: set[str] = set()
            unique: list[str] = []
            for c in candidates:
                c = c.lower().strip()
                if c in seen or len(c) > 120:
                    continue
                seen.add(c)
                unique.append(c)
            return unique

        def _pick_best_email(emails: list[str]) -> Optional[str]:
            if not emails:
                return None
            preferred = [u for u in emails if any(u.startswith(p) for p in ("info@", "contact@", "hello@", "admin@", "enquiry@", "enquiries@"))]
            return preferred[0] if preferred else emails[0]

        def _urls_to_scrape(soup, base_url: str) -> list[str]:
            parsed = urlparse(base_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            paths = ["/contact", "/contact-us", "/about", "/about-us", "/get-a-quote", "/enquire"]
            urls = []
            for p in paths:
                urls.append(urljoin(base, p))
            for a in soup.find_all("a", href=True):
                h = (a.get("href") or "").strip()
                if not h or h.startswith("#") or h.startswith("mailto:") or h.startswith("tel:"):
                    continue
                full = urljoin(base_url, h)
                if urlparse(full).netloc != parsed.netloc:
                    continue
                low = full.lower()
                if any(x in low for x in ("contact", "about", "quote", "enquir")):
                    urls.append(full)
            seen_urls: set[str] = set()
            deduped = []
            for u in urls:
                u = u.split("#")[0].rstrip("/") or u
                if u not in seen_urls:
                    seen_urls.add(u)
                    deduped.append(u)
            return deduped[:12]

        audited = 0
        for i, row in enumerate(rows):
            if i > 0:
                time.sleep(5)
            lead_id, name, website, existing_email = row[0], row[1], row[2], (row[3] if len(row) > 3 else None)
            suburb_lead = (row[4] if len(row) > 4 else None) or "Brisbane"
            if not website or not website.startswith("http"):
                website = "https://" + (website or "")
            _autopilot_log("audit", f"Auditing {name}", {"lead_id": lead_id})
            try:
                try:
                    import requests as req_lib
                    req_lib_session = req_lib.Session()
                    req_lib_session.headers.update({"User-Agent": "MotionMade Lead Audit"})
                    r = req_lib_session.get(website, timeout=12)
                    r.raise_for_status()
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(r.text, "html.parser")
                    all_emails: list[str] = []
                    emails_home = _collect_emails_from_page(soup, r.text)
                    all_emails.extend(emails_home)
                    extra_urls = _urls_to_scrape(soup, website)
                    for u in extra_urls:
                        if u == website.rstrip("/") or u == website:
                            continue
                        try:
                            r2 = req_lib_session.get(u, timeout=8)
                            if r2.status_code != 200:
                                continue
                            soup2 = BeautifulSoup(r2.text, "html.parser")
                            all_emails.extend(_collect_emails_from_page(soup2, r2.text))
                        except Exception:
                            continue
                    found_email = _pick_best_email(all_emails)
                    if not found_email and not (existing_email or "").strip():
                        _autopilot_log("audit", f"No email on site for {name}", {"lead_id": lead_id})
                    if found_email and not (existing_email or "").strip():
                        with get_conn() as conn_email:
                            conn_email.execute(
                                "UPDATE leads SET email = %s, updated_at = now() WHERE id = %s",
                                (found_email, lead_id),
                            )
                            conn_email.commit()
                    for tag in soup(["script", "style", "nav", "footer"]):
                        tag.decompose()
                    text = (soup.get_text(separator=" ", strip=True) or "")[:6000]
                except Exception as e:
                    _autopilot_log("audit", f"Could not fetch {website}: {e}", {"lead_id": lead_id})
                    detail = {"error": str(e), "score": 0}
                    with get_conn() as conn2:
                        conn2.execute(
                            "UPDATE leads SET status = 'audited', audit_score = 0, audit_details = %s, updated_at = now() WHERE id = %s",
                            (json.dumps(detail), lead_id),
                        )
                        conn2.commit()
                    audited += 1
                    continue

                prompt = f"""Analyze this business website content and score how much they need an AI FAQ/chat widget (MotionMade). Business: {name}. Website: {website}.

Consider: Do they already have a chat widget? Do they have a detailed FAQ page? Do they offer after-hours support? Is the site professional and likely to care about lead conversion?

Return a JSON object with:
- "score": number 1-10 (10 = high need: no chat, no FAQ, would benefit a lot)
- "has_chat_widget": boolean
- "has_faq_page": boolean
- "after_hours_support": boolean or null
- "notes": short string

Only return the JSON object, no other text."""

                try:
                    resp = _llm_retry("audit", lambda: client.chat.completions.create(
                        model="gpt-4o",
                        max_tokens=1024,
                        messages=[{"role": "user", "content": f"Website text:\n{text}\n\n{prompt}"}],
                    ))
                    text_out = (resp.choices[0].message.content or "").strip()
                    if text_out.startswith("```"):
                        text_out = re.sub(r"^```(?:json)?\s*", "", text_out)
                        text_out = re.sub(r"\s*```$", "", text_out)
                    detail = json.loads(text_out)
                    score = int(detail.get("score", 5))
                    if score < 1 or score > 10:
                        score = 5
                except Exception as e:
                    detail = {"error": str(e), "score": 5}
                    score = 5

                with get_conn() as conn2:
                    conn2.execute(
                        "UPDATE leads SET status = 'audited', audit_score = %s, audit_details = %s, updated_at = now() WHERE id = %s",
                        (score, json.dumps(detail) if isinstance(detail, dict) else "{}", lead_id),
                    )
                    conn2.commit()
                    audited += 1
            except Exception as lead_err:
                tb = traceback.format_exc()
                _autopilot_log("audit", f"Skip lead {name} (id={lead_id}): {lead_err}", {"lead_id": lead_id, "error": str(lead_err), "traceback": tb})
                continue

        _autopilot_log("audit", f"Audited {audited} leads", {"count": audited})
        return {"ok": True, "audited": audited}
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[AUDIT] {tb}")
        _autopilot_log("audit", str(e), {"traceback": tb})
        raise HTTPException(status_code=500, detail=f"Audit failed:\n{tb}")


@app.post("/api/leads/autopilot/preview")
def api_autopilot_preview(
    body: Optional[dict] = None,
    authorization: str = Header(default=""),
):
    """Generate demo previews for all leads that have a website (status audited or new). No threshold. Admin-only."""
    _check_admin_auth(authorization)
    try:
        with get_conn() as conn:
            rows = conn.execute(
                """SELECT id, business_name, website FROM leads
                   WHERE (website IS NOT NULL AND website != '') AND (preview_url IS NULL OR preview_url = '')
                   ORDER BY id"""
            ).fetchall()

        generated = 0
        for row in rows:
            lead_id, name, website = row[0], row[1], row[2]
            if not website:
                continue
            _autopilot_log("preview", f"Generating demo for {name}", {"lead_id": lead_id})
            try:
                # Call in-process to avoid self-HTTP deadlock on single-worker
                data = _create_demo_internal(name or "Business", website)
                demo_id = data.get("demo_id")
                preview_url = data.get("preview_url", "")
                with get_conn() as conn2:
                    conn2.execute(
                        "UPDATE leads SET preview_url = %s, preview_demo_id = %s, status = 'previewed', updated_at = now() WHERE id = %s",
                        (preview_url, demo_id, lead_id),
                    )
                    conn2.commit()
                generated += 1
            except Exception as e:
                _autopilot_log("preview", f"Failed {name}: {str(e)}", {"lead_id": lead_id, "error": str(e)})

        _autopilot_log("preview", f"Generated {generated} previews", {"count": generated})
        return {"ok": True, "generated": generated}
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[PREVIEW] {tb}")
        _autopilot_log("preview", str(e), {"traceback": tb})
        raise HTTPException(status_code=500, detail=f"Preview failed:\n{tb}")


@app.post("/api/leads/autopilot/email-writing")
def api_autopilot_email_writing(
    body: Optional[dict] = None,
    authorization: str = Header(default=""),
):
    """Use OpenAI GPT-4o to write personalised cold emails for each lead. Only processes audited/previewed (never re-writes ready/emailed). Admin-only."""
    _check_admin_auth(authorization)
    try:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")

        with get_conn() as conn:
            rows = conn.execute(
                """SELECT id, business_name, email, preview_url, suburb, audit_details, trade_type FROM leads
                   WHERE status IN ('audited', 'previewed') AND email IS NOT NULL AND email != ''
                   ORDER BY id"""
            ).fetchall()

        import openai
        client = openai.OpenAI(api_key=api_key)
        written = 0
        used_subjects: list[str] = []
        for i, row in enumerate(rows):
            if i > 0:
                time.sleep(5)
            lead_id, name, email, preview_url, suburb = row[0], row[1], row[2], row[3], row[4]
            audit_details = row[5] if len(row) > 5 else None
            trade_type = (row[6] if len(row) > 6 else None) or ""
            if isinstance(audit_details, dict):
                audit_summary = ", ".join(f"{k}: {v}" for k, v in audit_details.items() if v is not None and k != "error")
            else:
                audit_summary = str(audit_details) if audit_details else ""
            _autopilot_log("email", f"Writing email for {name}", {"lead_id": lead_id})

            used_subjects_instruction = ""
            if used_subjects:
                used_subjects_instruction = '\n\nSubject lines already used in this batch (use a DIFFERENT pattern and phrasing, do not repeat):\n' + "\n".join(f"- {s}" for s in used_subjects[-15:])

            trade_lower = (trade_type or "").lower()
            if "bond" in trade_lower:
                trade_angle = """This lead is a BOND CLEANING business. Their customers ask: how much for a 3 bedroom, do you do carpets, bond guarantee, what's included. Angle: customers google these at 9pm when moving out; if the site can't answer instantly they call someone else. Bond cleaning is time sensitive so instant answers mean more bookings. Mention MotionMade briefly (AI on their site that answers these 24/7, free trial). No generic chat widget pitch."""
            elif "house" in trade_lower or "home" in trade_lower or "domestic" in trade_lower:
                trade_angle = """This lead is a HOUSE CLEANING business. Customers want pricing, frequency, products, insurance. Angle: most people compare 3 or 4 cleaners before booking; the one that answers fastest wins. House cleaning is repeat business so one lost lead is months of lost income. Mention MotionMade briefly. No generic pitch."""
            else:
                trade_angle = """This lead is a PLUMBER. Customers ask about emergencies, "do you service my area", pricing, availability. Angle: someone with a burst pipe at 11pm won't wait for a call back tomorrow; if the website says you service their area and gives a rough price they'll book on the spot. Plumbers lose emergency jobs to whoever answers first. Mention MotionMade briefly. No generic pitch."""
            prompt = f"""Write a short cold email to this business lead.

Business: {name}. Suburb: {suburb or 'Brisbane'}. Their email: {email}.

{trade_angle}
"""
            if audit_summary:
                prompt += f"\nWhat we know about their website (reference something specific if you can): {audit_summary}\n"
            abbed_phone = (os.getenv("ABBED_PHONE") or "").strip()
            if abbed_phone:
                prompt += f"\nUse this phone number in the CTA: {abbed_phone}. E.g. 'give me a call on {abbed_phone}' or 'give me a bell on {abbed_phone}'.\n"
            else:
                prompt += "\nNo phone number provided. In the CTA just say something like 'reply to this email or shoot me a message' (no phone).\n"
            prompt += """
STRICT RULES:
1. NEVER use hyphens or em dashes as punctuation. No "—" and no "-" between phrases. Use full stops or commas only. This is a dead giveaway of AI text.
2. Subject line: be direct about the product, not clickbait. The subject must clearly communicate that this is an AI tool that helps them convert more leads. Examples: "AI that books jobs for your cleaning business while you sleep" / "an AI front desk for [Business Name]" / "AI that answers your customers' questions 24/7" / "stop losing after hours leads, [Business Name]" / "AI tool built for Brisbane bond cleaners". Still vary them, but be upfront that it's AI and that it helps convert leads. No tricks or misleading subjects.
3. Body: sound like a text message from a mate, not a sales pitch. Short sentences. No fancy words. No marketing language. No "leverage", "streamline", "solution", "empower" or any corporate buzzwords. Write like a 27 year old Brisbane bloke would actually write an email. Make it clear this isn't a generic chatbot: mention that the AI answers based on the business's own FAQs and info (e.g. "it learns your pricing, your services, your areas, and answers customers based on your actual business info" or "it answers based on your own FAQs, not generic responses"). This is a key differentiator.
4. Always include the link https://motionmadebne.com.au in the email body. Add a line near the end like "Check it out here: https://motionmadebne.com.au" or weave it naturally into the CTA. Use the full URL so it's clickable.
5. Every email must end with a friendly, approachable call to action before the sign-off. Something like "If you want to see how it works or have any questions, just reply to this email or give me a call on [phone]." Make it feel like a real person offering help, not a sales pitch. Never say "schedule a call" or "book a demo". Keep it casual: "give me a bell", "flick me a reply", "reply to this email or shoot me a message" are good. If a phone number is provided below, use it in the CTA; otherwise just say "reply to this email or shoot me a message".
6. Every email must be different. Vary the opening, the angle, the structure. Some start with a question, some with an observation, some are only 3 sentences. Never repeat the same pattern twice in this batch.
7. Sign off as just "Abbed". No title, no company name, no footer.

Return ONLY the email body (plain text). Then on the next line write "---SUBJECT---" and then the subject line.
"""
            if preview_url:
                prompt += f"\nOptional: they have a preview link you can mention (no signup): {preview_url}"
            prompt += used_subjects_instruction

            try:
                resp = _llm_retry("email", lambda: client.chat.completions.create(
                    model="gpt-4o",
                    max_tokens=1024,
                    messages=[{"role": "user", "content": prompt}],
                ))
                text_out = (resp.choices[0].message.content or "").strip()
                if "---SUBJECT---" in text_out:
                    body_text, subject = text_out.split("---SUBJECT---", 1)
                    body_text = body_text.strip()
                    subject = subject.strip()
                else:
                    subject = f"Had an idea for {name}"
                    body_text = text_out
                used_subjects.append(subject)
                with get_conn() as conn2:
                    conn2.execute(
                        "UPDATE leads SET email_subject = %s, email_body = %s, status = 'ready', updated_at = now() WHERE id = %s",
                        (subject, body_text, lead_id),
                    )
                    conn2.commit()
                written += 1
            except Exception as e:
                _autopilot_log("email", f"Failed {name}: {str(e)}", {"lead_id": lead_id, "error": str(e)})

        _autopilot_log("email", f"Wrote {written} emails", {"count": written})
        return {"ok": True, "written": written}
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[EMAIL-WRITING] {tb}")
        _autopilot_log("email", str(e), {"traceback": tb})
        raise HTTPException(status_code=500, detail=f"Email writing failed:\n{tb}")


@app.post("/api/leads/autopilot/send-ready")
def api_leads_autopilot_send_ready(authorization: str = Header(default="")):
    """Send all ready leads via Gmail SMTP. Respects DAILY_EMAIL_LIMIT. Admin-only."""
    _check_admin_auth(authorization)
    gmail_user = (os.getenv("GMAIL_ADDRESS") or "").strip()
    gmail_pass = (os.getenv("GMAIL_APP_PASSWORD") or "").strip()
    if not gmail_user or not gmail_pass:
        raise HTTPException(
            status_code=500,
            detail="GMAIL_ADDRESS and GMAIL_APP_PASSWORD must be set",
        )
    limit = _daily_email_limit()
    with get_conn() as conn:
        today_count_row = conn.execute(
            """SELECT COUNT(*) FROM leads
               WHERE status = 'emailed'
               AND (updated_at AT TIME ZONE 'Australia/Brisbane')::date = (CURRENT_TIMESTAMP AT TIME ZONE 'Australia/Brisbane')::date"""
        ).fetchone()
    today_sent = today_count_row[0] if today_count_row else 0
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, business_name, email, email_subject, email_body
               FROM leads
               WHERE status = 'ready' AND email IS NOT NULL AND email != ''
               ORDER BY id"""
        ).fetchall()
    sent = 0
    failed = 0
    skipped_limit = 0
    for i, row in enumerate(rows):
        if today_sent >= limit:
            skipped_limit += 1
            _autopilot_log("send", f"Skipped (daily limit): {row[1]}", {"lead_id": row[0]})
            continue
        lead_id, name, email, subj, body = row[0], row[1], row[2], row[3], row[4]
        to_addr = (email or "").strip()
        if not to_addr:
            continue
        subject = (subj or f"MotionMade demo for {name}").strip()
        body_text = (body or "").strip()
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"Abbed <{gmail_user}>"
            msg["To"] = to_addr
            msg["Reply-To"] = "abbed@motionmadebne.com.au"
            msg.attach(MIMEText(body_text, "plain", "utf-8"))
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(gmail_user, gmail_pass)
                server.sendmail(gmail_user, to_addr, msg.as_string())
            with get_conn() as conn2:
                conn2.execute(
                    "UPDATE leads SET status = 'emailed', updated_at = now() WHERE id = %s",
                    (lead_id,),
                )
                conn2.commit()
            sent += 1
            today_sent += 1
            _autopilot_log("send", f"Sending email to {to_addr}... Sent ✓", {"lead_id": lead_id})
        except Exception as e:
            failed += 1
            _autopilot_log("send", f"Sending email to {to_addr}... Failed: {e}", {"lead_id": lead_id, "error": str(e)})
        if i < len(rows) - 1:
            time.sleep(30)
    return {"ok": True, "sent": sent, "failed": failed, "skipped_limit": skipped_limit}


@app.post("/api/leads/send-all-ready")
def api_leads_send_all_ready(
    authorization: str = Header(default=""),
):
    """Send all emails with status 'ready'. 30 second delay between each. Admin-only."""
    _check_admin_auth(authorization)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, business_name, email, email_subject, email_body FROM leads WHERE status = 'ready' AND email IS NOT NULL AND email != ''"
        ).fetchall()

    base_url = os.getenv("PUBLIC_BASE_URL") or "https://motionmade-fastapi.onrender.com"
    if not base_url.startswith("http"):
        base_url = "https://" + base_url
    auth_header = f"Bearer {settings.ADMIN_TOKEN}"
    sent = 0
    for i, row in enumerate(rows):
        lead_id, name, email, subj, body = row[0], row[1], row[2], row[3], row[4]
        if i > 0:
            time.sleep(30)
        try:
            import requests as req_lib
            r = req_lib.post(
                f"{base_url}/api/outreach/send",
                json={
                    "to_email": email,
                    "subject": subj or f"MotionMade demo for {name}",
                    "body": body or "",
                    "from_name": "Abbed",
                    "reply_to": "abbed@motionmadebne.com.au",
                    "lead_name": name,
                },
                headers={"Authorization": auth_header, "Content-Type": "application/json"},
                timeout=30,
            )
            r.raise_for_status()
            with get_conn() as conn2:
                conn2.execute("UPDATE leads SET status = 'emailed', updated_at = now() WHERE id = %s", (lead_id,))
                conn2.commit()
            sent += 1
            _autopilot_log("send", f"Sent to {name}", {"lead_id": lead_id})
        except Exception as e:
            _autopilot_log("send", f"Failed to send to {name}: {str(e)}", {"lead_id": lead_id, "error": str(e)})

    return {"ok": True, "sent": sent, "total_ready": len(rows)}


# Owner FAQ write endpoints removed — quality controlled by admin only
# POST /owner/faqs, PUT /owner/faqs/{id}, DELETE /owner/faqs/{id} are disabled.
# Owners can only view FAQs via GET /owner/faqs.


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
    """List all tenants with live FAQ count, queries this week, owner email, and status."""
    _check_admin_auth(authorization)
    
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT t.id, t.name, t.business_type, t.created_at,
                   COALESCE(faq.cnt, 0) AS live_faq_count,
                   COALESCE(q7.qc, 0) AS queries_this_week,
                   o.owner_email
            FROM tenants t
            LEFT JOIN (SELECT tenant_id, COUNT(*) AS cnt FROM faq_items WHERE is_staged = false GROUP BY tenant_id) faq ON faq.tenant_id = t.id
            LEFT JOIN (SELECT tenant_id, COUNT(*) AS qc FROM telemetry WHERE created_at > now() - interval '7 days' GROUP BY tenant_id) q7 ON q7.tenant_id = t.id
            LEFT JOIN (SELECT tenant_id, MIN(email) AS owner_email FROM tenant_owners GROUP BY tenant_id) o ON o.tenant_id = t.id
            ORDER BY t.created_at DESC
        """).fetchall()
    
    tenants = [
        {
            "id": row[0],
            "name": row[1] or row[0],
            "business_type": row[2] or None,
            "created_at": row[3].isoformat() if row[3] else None,
            "live_faq_count": int(row[4]),
            "queries_this_week": int(row[5]),
            "active": int(row[5]) > 0,
            "owner_email": (row[6] or "").strip() or None,
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
    business_type = (tenant.business_type or "").strip() or None
    contact_phone = (tenant.contact_phone or "").strip() or None
    
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    
    try:
        with get_conn() as conn:
            conn.execute(
                """INSERT INTO tenants (id, name, business_type, contact_phone)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET
                     name = EXCLUDED.name,
                     business_type = COALESCE(EXCLUDED.business_type, tenants.business_type),
                     contact_phone = COALESCE(EXCLUDED.contact_phone, tenants.contact_phone)""",
                (tenant_id, tenant_name or tenant_id, business_type, contact_phone),
            )
            conn.commit()
        
        return {"id": tenant_id, "name": tenant_name or tenant_id, "business_type": business_type, "contact_phone": contact_phone, "created": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create tenant: {str(e)}")


@app.get("/admin/api/tenant/{tenantId}")
def get_tenant_detail(tenantId: str, resp: Response, authorization: str = Header(default="")):
    """Get tenant details including domains, staged FAQ count, and last run status."""
    _check_admin_auth(authorization)
    
    import json as json_lib
    
    with get_conn() as conn:
        tenant_row = conn.execute(
            "SELECT id, name, business_type, contact_phone, created_at FROM tenants WHERE id = %s",
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
        "business_type": tenant_row[2] if len(tenant_row) > 2 else None,
        "contact_phone": tenant_row[3] if len(tenant_row) > 3 else None,
        "created_at": tenant_row[4].isoformat() if len(tenant_row) > 4 and tenant_row[4] else None,
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


@app.get("/admin/api/tenant/{tenantId}/queries")
def admin_get_tenant_queries(
    tenantId: str,
    days: int = 7,
    limit: int = 50,
    authorization: str = Header(default=""),
):
    """Get query log for a specific tenant (admin view). Same data as owner dashboard."""
    _check_admin_auth(authorization)
    tid = (tenantId or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    days = max(1, min(365, days))
    limit = max(1, min(200, limit))
    with get_conn() as conn:
        where = "tenant_id = %s AND created_at > now() - (%s::text || ' days')::interval"
        params = [tid, str(days)]
        total_row = conn.execute(
            f"SELECT COUNT(*) FROM query_log WHERE {where}",
            params,
        ).fetchone()
        total = total_row[0] or 0
        rows = conn.execute(
            f"""SELECT id, customer_question, answer_given, matched_faq, was_fallback, created_at
                FROM query_log WHERE {where}
                ORDER BY created_at DESC
                LIMIT %s OFFSET 0""",
            params + [limit],
        ).fetchall()
    queries = [
        {
            "id": r[0],
            "question": (r[1] or "").strip(),
            "answer": (r[2] or "").strip() or None,
            "matched_to": (r[3] or "").strip() or None,
            "answered": not (r[4] or False),
            "timestamp": r[5].isoformat() if r[5] else None,
        }
        for r in rows
    ]
    return {"tenant_id": tid, "queries": queries, "total": total, "period_days": days}


@app.get("/admin/api/tenant/{tenantId}/owner")
def get_tenant_owner(
    tenantId: str,
    authorization: str = Header(default=""),
):
    """Get owner account for a tenant. Returns 404 if no owner."""
    _check_admin_auth(authorization)
    tid = (tenantId or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT email, display_name, last_login, created_at FROM tenant_owners WHERE tenant_id = %s LIMIT 1",
            (tid,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No owner account for this tenant")
    return {
        "email": row[0],
        "display_name": (row[1] or "").strip() or None,
        "last_login": row[2].isoformat() if row[2] else None,
        "created_at": row[3].isoformat() if row[3] else None,
    }


@app.post("/admin/api/tenant/{tenantId}/owner/reset-password")
def reset_tenant_owner_password(
    tenantId: str,
    authorization: str = Header(default=""),
):
    """Generate a new random password for the tenant's owner, store hash, return plain password."""
    _check_admin_auth(authorization)
    import secrets
    tid = (tenantId or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    new_password = "TempPass_" + secrets.token_hex(4)
    password_hash = _hash_password(new_password)
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE tenant_owners SET password_hash = %s WHERE tenant_id = %s RETURNING email",
            (password_hash, tid),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No owner account for this tenant")
    return {"email": row[0], "new_password": new_password}


@app.delete("/admin/api/tenant/{tenantId}/owner")
def delete_tenant_owner(
    tenantId: str,
    authorization: str = Header(default=""),
):
    """Delete the owner account for this tenant."""
    _check_admin_auth(authorization)
    tid = (tenantId or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    with get_conn() as conn:
        conn.execute("DELETE FROM tenant_owners WHERE tenant_id = %s", (tid,))
        conn.commit()
    return {"deleted": True, "tenant_id": tid}


# ---------- Admin: FAQ suggestions (review / approve / reject) ----------
class SuggestionApproveBody(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None


class SuggestionRejectBody(BaseModel):
    note: Optional[str] = None


@app.get("/admin/api/tenant/{tenantId}/suggestions")
def admin_list_suggestions(
    tenantId: str,
    authorization: str = Header(default=""),
):
    """List all FAQ suggestions for a tenant (admin)."""
    _check_admin_auth(authorization)
    tid = (tenantId or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, suggested_question, suggested_answer, status, created_at, reviewed_at, reviewer_note
               FROM faq_suggestions WHERE tenant_id = %s ORDER BY created_at DESC""",
            (tid,),
        ).fetchall()
    suggestions = [
        {
            "id": r[0],
            "question": r[1],
            "answer": r[2],
            "status": r[3],
            "created_at": r[4].isoformat() if r[4] else None,
            "reviewed_at": r[5].isoformat() if r[5] else None,
            "reviewer_note": r[6],
        }
        for r in rows
    ]
    return {"suggestions": suggestions}


@app.post("/admin/api/tenant/{tenantId}/suggestions/{suggestion_id}/approve")
def admin_approve_suggestion(
    tenantId: str,
    suggestion_id: int,
    body: Optional[SuggestionApproveBody] = None,
    authorization: str = Header(default=""),
):
    """Approve a suggestion: add as FAQ (optionally with edited Q/A), stage and promote to live."""
    _check_admin_auth(authorization)
    tid = (tenantId or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, suggested_question, suggested_answer FROM faq_suggestions WHERE id = %s AND tenant_id = %s",
            (suggestion_id, tid),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        sug_q = (row[1] or "").strip()
        sug_a = (row[2] or "").strip() or ""
    question = ((body.question if body else None) or "").strip() or sug_q
    answer = ((body.answer if body else None) or "").strip() or sug_a
    if not question:
        raise HTTPException(status_code=400, detail="Question required")
    # Build list: current live FAQs + new one
    with get_conn() as conn:
        live = conn.execute(
            "SELECT question, answer FROM faq_items WHERE tenant_id = %s AND is_staged = false ORDER BY id",
            (tid,),
        ).fetchall()
    items = [{"question": r[0], "answer": r[1]} for r in live]
    items.append({"question": question, "answer": answer})
    _stage_faqs_internal(tid, items)
    # Promote via HTTP to reuse full pipeline (suite, etc.)
    base_url = os.getenv("PUBLIC_BASE_URL") or ("http://127.0.0.1:8000" if not os.getenv("RENDER") else "https://motionmade-fastapi.onrender.com")
    import requests as req_lib
    try:
        promo = req_lib.post(
            f"{base_url}/admin/api/tenant/{tid}/promote",
            headers={"Authorization": f"Bearer {settings.ADMIN_TOKEN}"},
            timeout=180,
        )
        promo.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Staged OK but promote failed: {str(e)}")
    # Mark suggestion approved
    with get_conn() as conn:
        conn.execute(
            "UPDATE faq_suggestions SET status = 'approved', reviewed_at = now() WHERE id = %s AND tenant_id = %s",
            (suggestion_id, tid),
        )
        conn.commit()
    return {"approved": True, "suggestion_id": suggestion_id, "message": "FAQ added and promoted to live"}


@app.post("/admin/api/tenant/{tenantId}/suggestions/{suggestion_id}/reject")
def admin_reject_suggestion(
    tenantId: str,
    suggestion_id: int,
    body: Optional[SuggestionRejectBody] = None,
    authorization: str = Header(default=""),
):
    """Reject a suggestion. Optional note for the owner."""
    _check_admin_auth(authorization)
    tid = (tenantId or "").strip()
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    note = (body.note if body else None) or ""
    note = (note.strip() or None) if isinstance(note, str) else None
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE faq_suggestions SET status = 'rejected', reviewed_at = now(), reviewer_note = %s WHERE id = %s AND tenant_id = %s RETURNING id",
            (note, suggestion_id, tid),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Suggestion not found")
        conn.commit()
    return {"rejected": True, "suggestion_id": suggestion_id}


# ---------- FAQ templates (admin: fast onboarding) ----------
_FAQ_TEMPLATES_PATH = Path(__file__).resolve().parent / "templates" / "faq_templates.json"


def _load_faq_templates() -> dict:
    """Load faq_templates.json. Returns {} if missing."""
    if not _FAQ_TEMPLATES_PATH.exists():
        return {}
    try:
        with open(_FAQ_TEMPLATES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _substitute_variables(text: str, variables: dict) -> str:
    """Replace ${key} in text with variables.get(key, '')."""
    if not text or not isinstance(text, str):
        return text or ""
    result = text
    for k, v in (variables or {}).items():
        result = result.replace("${" + k + "}", str(v))
    return result


@app.get("/admin/api/faq-templates")
def admin_get_faq_templates(authorization: str = Header(default="")):
    """Return all FAQ templates (cleaner, plumber, electrician). ADMIN_TOKEN protected."""
    _check_admin_auth(authorization)
    return _load_faq_templates()


@app.get("/admin/api/faq-templates/{template_type}")
def admin_get_faq_template(
    template_type: str,
    authorization: str = Header(default=""),
    request: Request = None,
):
    """Return one template with variables. Query params override template variables."""
    _check_admin_auth(authorization)
    templates = _load_faq_templates()
    key = (template_type or "").strip().lower()
    if key not in templates:
        raise HTTPException(status_code=404, detail=f"Template '{template_type}' not found")
    tpl = templates[key]
    variables = dict(tpl.get("variables") or {})
    if request and request.query_params:
        for name, value in request.query_params.items():
            variables[name] = value
    faqs = []
    for faq in tpl.get("faqs") or []:
        q = _substitute_variables(faq.get("question") or "", variables)
        a = _substitute_variables(faq.get("answer") or "", variables)
        faqs.append({"question": q, "answer": a})
    return {
        "display_name": tpl.get("display_name") or key,
        "faqs": faqs,
        "variables": variables,
    }


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


@app.delete("/admin/api/tenant/{tenantId}")
def delete_tenant(
    tenantId: str,
    authorization: str = Header(default=""),
):
    """Delete a tenant and all related data. Protected by ADMIN_TOKEN."""
    _check_admin_auth(authorization)
    tid = tenantId.strip()
    if not tid:
        raise HTTPException(status_code=400, detail="Tenant ID required")
    try:
        with get_conn() as conn:
            conn.execute("DELETE FROM retrieval_cache WHERE tenant_id = %s", (tid,))
            conn.execute("DELETE FROM telemetry WHERE tenant_id = %s", (tid,))
            conn.execute("DELETE FROM query_stats WHERE tenant_id = %s", (tid,))
            conn.execute("DELETE FROM query_log WHERE tenant_id = %s", (tid,))
            conn.execute("DELETE FROM tenant_promote_history WHERE tenant_id = %s", (tid,))
            conn.execute("DELETE FROM tenant_owners WHERE tenant_id = %s", (tid,))
            conn.execute("DELETE FROM tenant_domains WHERE tenant_id = %s", (tid,))
            conn.execute("DELETE FROM faq_suggestions WHERE tenant_id = %s", (tid,))
            conn.execute(
                "DELETE FROM faq_variants WHERE faq_id IN (SELECT id FROM faq_items WHERE tenant_id = %s)",
                (tid,),
            )
            try:
                conn.execute("DELETE FROM faq_variants_p WHERE tenant_id = %s", (tid,))
            except Exception:
                pass
            conn.execute("DELETE FROM faq_items WHERE tenant_id = %s", (tid,))
            conn.execute("DELETE FROM faq_items_last_good WHERE tenant_id = %s", (tid,))
            conn.execute("DELETE FROM tenants WHERE id = %s", (tid,))
            conn.commit()
        return {"deleted": True, "tenant_id": tid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete tenant: {str(e)}")


def _stage_faqs_internal(tenant_id: str, items: List[dict]) -> int:
    """Stage FAQs: delete existing staged, insert items. Items are [{"question", "answer"}, ...]. Returns count."""
    import json as json_lib
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            (tenant_id, tenant_id),
        )
        conn.execute(
            "DELETE FROM faq_variants WHERE faq_id IN (SELECT id FROM faq_items WHERE tenant_id=%s AND is_staged=true)",
            (tenant_id,),
        )
        conn.execute("DELETE FROM faq_items WHERE tenant_id=%s AND is_staged=true", (tenant_id,))
        count = 0
        for it in items:
            q = (it.get("question") or "").strip()
            a = (it.get("answer") or "").strip()
            if not q or not a:
                continue
            emb_q = embed_text(q)
            raw_variants = it.get("variants") or []
            if isinstance(raw_variants, str):
                try:
                    raw_variants = json_lib.loads(raw_variants)
                except Exception:
                    raw_variants = []
            variants_json = json_lib.dumps(raw_variants) if raw_variants else "[]"
            conn.execute(
                "INSERT INTO faq_items (tenant_id, question, answer, embedding, enabled, is_staged, variants_json) "
                "VALUES (%s,%s,%s,%s,true,true,%s)",
                (tenant_id, q, a, Vector(emb_q), variants_json),
            )
            count += 1
        conn.commit()
    return count


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
        items_data = [{"question": it.question, "answer": it.answer, "variants": it.variants} for it in items]
        count = _stage_faqs_internal(tenantId, items_data)
        
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
            # Ensure partition exists for this tenant
            conn.execute("SELECT ensure_faq_variants_partition(%s)", (tenantId,))
            conn.commit()
            
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
                
                # Delete old variants from both tables
                conn.execute("DELETE FROM faq_variants WHERE faq_id=%s", (faq_id,))
                conn.execute("DELETE FROM faq_variants_p WHERE faq_id=%s AND tenant_id=%s", (faq_id, tenantId))
                
                # Embed all variants (limit to 50 per FAQ)
                embedded_count = 0
                for variant in all_variants[:50]:
                    variant = variant.strip()
                    if not variant:
                        continue
                    
                    try:
                        v_emb = embed_text(variant)
                        # Insert into old table (for backward compatibility during migration)
                        conn.execute("""
                            INSERT INTO faq_variants (faq_id, variant_question, variant_embedding, enabled)
                            VALUES (%s, %s, %s, true)
                        """, (faq_id, variant, Vector(v_emb)))
                        # Insert into partitioned table (primary)
                        conn.execute("""
                            INSERT INTO faq_variants_p (tenant_id, faq_id, variant_question, variant_embedding, enabled)
                            VALUES (%s, %s, %s, %s, true)
                        """, (tenantId, faq_id, variant, Vector(v_emb)))
                        embedded_count += 1
                    except Exception as e:
                        print(f"Embed error for '{variant[:30]}': {e}")
                        # Continue with next variant instead of failing entire promote
                        continue
                
                print(f"Embedded {embedded_count} variants for FAQ '{q}' (faq_id={faq_id})")
            
            # Update search vectors for FTS after promotion - include variants
            try:
                # Get all promoted FAQs with their variants
                promoted_faqs = conn.execute("""
                    SELECT fi.id, fi.question, fi.answer, fi.variants_json
                    FROM faq_items fi
                    WHERE fi.tenant_id = %s AND fi.is_staged = false
                """, (tenantId,)).fetchall()
                
                for faq_row in promoted_faqs:
                    faq_id, question, answer, variants_json = faq_row
                    # Parse variants
                    variants = []
                    if variants_json:
                        try:
                            if isinstance(variants_json, str):
                                variants = json_lib.loads(variants_json)
                            elif isinstance(variants_json, list):
                                variants = variants_json
                        except:
                            variants = []
                    
                    # Build weighted FTS vector: prioritize question/variants over answer text
                    question_variants_text = (question or "") + " " + " ".join(variants)
                    answer_text = answer or ""
                    
                    conn.execute("""
                        UPDATE faq_items 
                        SET search_vector =
                            setweight(to_tsvector('english', %s), 'A') ||
                            setweight(to_tsvector('english', %s), 'C')
                        WHERE id = %s
                    """, (question_variants_text, answer_text, faq_id))
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
                
                conn.commit()
                
                # Invalidate tenant FAQ count cache (count may have changed)
                _invalidate_tenant_count_cache(tenantId)
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
                conn.execute("""
                    DELETE FROM faq_variants_p WHERE tenant_id=%s
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
                    # Insert into old table
                    conn.execute("""
                        INSERT INTO faq_variants (faq_id, variant_question, variant_embedding, enabled)
                        VALUES (%s, %s, %s, true)
                    """, (faq_id, q, Vector(q_emb)))
                    # Insert into partitioned table
                    conn.execute("""
                        INSERT INTO faq_variants_p (tenant_id, faq_id, variant_question, variant_embedding, enabled)
                        VALUES (%s, %s, %s, %s, true)
                    """, (tenantId, faq_id, q, Vector(q_emb)))
                
                # Log failure
                conn.execute("""
                    INSERT INTO tenant_promote_history (tenant_id, status, suite_result, first_failure)
                    VALUES (%s, 'failed', %s, %s)
                """, (tenantId, json_lib.dumps(suite_result), json_lib.dumps(suite_result.get("first_failure"))))
            
            conn.commit()
        
        if should_promote:
            # Near-duplicate FAQ check (cosine similarity on question embeddings)
            warnings = []
            try:
                with get_conn() as conn:
                    rows = conn.execute("""
                        SELECT id, question, embedding FROM faq_items
                        WHERE tenant_id = %s AND is_staged = false AND embedding IS NOT NULL
                    """, (tenantId,)).fetchall()
                if len(rows) >= 2:
                    # Cosine similarity between each pair
                    def _cosine(a, b):
                        if not a or not b or len(a) != len(b):
                            return 0.0
                        dot = sum(x * y for x, y in zip(a, b))
                        na = sum(x * x for x in a) ** 0.5
                        nb = sum(y * y for y in b) ** 0.5
                        if na * nb == 0:
                            return 0.0
                        return dot / (na * nb)
                    # Embedding can be list or pgvector Vector
                    def _to_list(emb):
                        if emb is None:
                            return None
                        if hasattr(emb, "tolist"):
                            return emb.tolist()
                        if isinstance(emb, (list, tuple)):
                            return list(emb)
                        try:
                            return list(emb)
                        except Exception:
                            return None
                    for i in range(len(rows)):
                        for j in range(i + 1, len(rows)):
                            idi, qi, emi = rows[i]
                            idj, qj, emj = rows[j]
                            li, lj = _to_list(emi), _to_list(emj)
                            if li and lj:
                                sim = _cosine(li, lj)
                                if sim >= 0.85:
                                    warnings.append({
                                        "type": "similar_faqs",
                                        "faq_1": qi,
                                        "faq_2": qj,
                                        "similarity": round(sim, 2),
                                        "suggestion": "Consider merging these into one FAQ"
                                    })
            except Exception:
                pass
            return {
                "tenant_id": tenantId,
                "status": "success",
                "message": f"Promoted {staged_count} FAQs to live",
                "suite_result": suite_result,
                "warnings": warnings
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


@app.post("/admin/api/tenant/{tenantId}/regenerate-variants")
def regenerate_variants(
    tenantId: str,
    resp: Response,
    authorization: str = Header(default="")
):
    """Regenerate variants for all live FAQs using the current variant prompt (no re-upload)."""
    _check_admin_auth(authorization)
    import json as json_lib
    tenant_id = (tenantId or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id required")
    try:
        with get_conn() as conn:
            conn.execute("SELECT ensure_faq_variants_partition(%s)", (tenant_id,))
            conn.commit()
        live_faqs = None
        with get_conn() as conn:
            live_faqs = conn.execute("""
                SELECT id, question, answer FROM faq_items
                WHERE tenant_id = %s AND is_staged = false AND enabled = true
            """, (tenant_id,)).fetchall()
        if not live_faqs:
            return {"tenant_id": tenant_id, "regenerated": 0, "new_variants": 0, "message": "No live FAQs"}
        faqs_to_expand = [
            {"question": q, "answer": a, "variants": []}
            for _, q, a in live_faqs
        ]
        expanded_faqs = expand_faq_list(faqs_to_expand, max_variants_per_faq=50)
        expanded_map = {f["question"]: f.get("variants", []) for f in expanded_faqs}
        total_new_variants = 0
        with get_conn() as conn:
            for faq_id, q, a in live_faqs:
                variants = expanded_map.get(q, []) or []
                all_variants = [q] + [v for v in variants if v and (v or "").strip().lower() != (q or "").lower()]
                conn.execute("DELETE FROM faq_variants WHERE faq_id=%s", (faq_id,))
                conn.execute("DELETE FROM faq_variants_p WHERE faq_id=%s AND tenant_id=%s", (faq_id, tenant_id))
                for variant in all_variants[:50]:
                    v = (variant or "").strip()
                    if not v:
                        continue
                    try:
                        v_emb = embed_text(v)
                        conn.execute("""
                            INSERT INTO faq_variants (faq_id, variant_question, variant_embedding, enabled)
                            VALUES (%s, %s, %s, true)
                        """, (faq_id, v, Vector(v_emb)))
                        conn.execute("""
                            INSERT INTO faq_variants_p (tenant_id, faq_id, variant_question, variant_embedding, enabled)
                            VALUES (%s, %s, %s, %s, true)
                        """, (tenant_id, faq_id, v, Vector(v_emb)))
                        total_new_variants += 1
                    except Exception:
                        continue
                question_variants_text = (q or "") + " " + " ".join(all_variants[1:])
                answer_text = a or ""
                conn.execute("""
                    UPDATE faq_items SET search_vector =
                        setweight(to_tsvector('english', %s), 'A') ||
                        setweight(to_tsvector('english', %s), 'C')
                    WHERE id = %s
                """, (question_variants_text, answer_text, faq_id))
            conn.commit()
        return {
            "tenant_id": tenant_id,
            "regenerated": len(live_faqs),
            "new_variants": total_new_variants,
            "message": f"Regenerated variants for {len(live_faqs)} FAQs ({total_new_variants} variants)"
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Regenerate variants failed: {str(e)}")


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
            
            # Ensure partition exists
            conn.execute("SELECT ensure_faq_variants_partition(%s)", (tenantId,))
            conn.commit()
            
            # Delete current live FAQs
            conn.execute("DELETE FROM faq_items WHERE tenant_id=%s AND is_staged=false", (tenantId,))
            conn.execute("""
                DELETE FROM faq_variants 
                WHERE faq_id IN (SELECT id FROM faq_items WHERE tenant_id=%s)
            """, (tenantId,))
            conn.execute("DELETE FROM faq_variants_p WHERE tenant_id=%s", (tenantId,))
            
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
                # Insert into old table
                conn.execute("""
                    INSERT INTO faq_variants (faq_id, variant_question, variant_embedding, enabled)
                    VALUES (%s, %s, %s, true)
                """, (faq_id, q, Vector(q_emb)))
                # Insert into partitioned table
                conn.execute("""
                    INSERT INTO faq_variants_p (tenant_id, faq_id, variant_question, variant_embedding, enabled)
                    VALUES (%s, %s, %s, %s, true)
                """, (tenantId, faq_id, q, Vector(q_emb)))
            
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
            # Build patterns in Python to avoid psycopg3 placeholder issues
            priority_patterns = ['%beep%', '%chirp%', '%smoke%', '%alarm%']
            variant_samples = conn.execute("""
                SELECT variant_question 
                FROM faq_variants 
                WHERE faq_id = %s AND enabled = true
                ORDER BY 
                    CASE WHEN (
                        variant_question ILIKE %s OR 
                        variant_question ILIKE %s OR 
                        variant_question ILIKE %s OR 
                        variant_question ILIKE %s
                    ) THEN 0 ELSE 1 END,
                    id
                LIMIT 20
            """, (faq_id, priority_patterns[0], priority_patterns[1], priority_patterns[2], priority_patterns[3])).fetchall()
            
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


@app.post("/admin/api/db/analyze")
async def analyze_tables(
    request: Request,
    authorization: str = Header(default="")
):
    """
    Admin-only endpoint to run ANALYZE on specified tables.
    Body: {"tables": ["faq_variants", "faq_items"]}
    """
    _check_admin_auth(authorization)
    
    try:
        body = await request.json()
        tables = body.get("tables", [])
        if not tables:
            raise HTTPException(status_code=400, detail="tables array required")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON body: {str(e)}")
    
    results = []
    with get_conn() as conn:
        for table in tables:
            try:
                # Validate table name to prevent SQL injection
                if not table.replace("_", "").replace("-", "").isalnum():
                    results.append({"table": table, "status": "error", "error": "Invalid table name"})
                    continue
                
                # Run ANALYZE
                conn.execute(f"ANALYZE {table}")
                conn.commit()
                results.append({"table": table, "status": "success"})
            except Exception as e:
                results.append({"table": table, "status": "error", "error": str(e)})
    
    return {
        "analyzed_tables": results,
        "total": len(results),
        "success_count": len([r for r in results if r["status"] == "success"])
    }


@app.post("/admin/api/db/create_faq_variants_partitioned")
async def create_faq_variants_partitioned(
    authorization: str = Header(default="")
):
    """
    Admin-only endpoint to manually create the faq_variants_p partitioned table.
    Returns success/error with full PostgreSQL error message if it fails.
    """
    _check_admin_auth(authorization)
    
    try:
        with get_conn() as conn:
            # Create sequence first (required for DEFAULT in table definition)
            conn.execute("""
                CREATE SEQUENCE IF NOT EXISTS faq_variants_p_id_seq
            """)
            
            # Create the partitioned parent table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS faq_variants_p (
                  id BIGINT NOT NULL DEFAULT nextval('faq_variants_p_id_seq'),
                  tenant_id TEXT NOT NULL,
                  faq_id BIGINT NOT NULL REFERENCES faq_items(id) ON DELETE CASCADE,
                  variant_question TEXT NOT NULL,
                  variant_embedding vector(1536) NOT NULL,
                  enabled BOOLEAN NOT NULL DEFAULT true,
                  updated_at TIMESTAMPTZ DEFAULT now(),
                  PRIMARY KEY (tenant_id, id)
                ) PARTITION BY LIST (tenant_id)
            """)
            
            conn.commit()
            
            return {
                "ok": True,
                "message": "faq_variants_p partitioned table created successfully"
            }
    except Exception as e:
        error_msg = str(e)
        import traceback
        traceback.print_exc()
        return {
            "ok": False,
            "error": error_msg,
            "error_type": type(e).__name__
        }


@app.post("/admin/api/db/ensure_partition/{tenantId}")
async def ensure_partition_for_tenant(
    tenantId: str,
    authorization: str = Header(default="")
):
    """
    Admin-only endpoint to ensure a partition exists for a tenant and create its ivfflat index.
    Returns partition name and index creation status.
    """
    _check_admin_auth(authorization)
    
    try:
        with get_conn() as conn:
            # Call the helper function
            conn.execute("SELECT ensure_faq_variants_partition(%s)", (tenantId,))
            conn.commit()
            
            # Get partition name (sanitized)
            import re
            sanitized_tenant = re.sub(r'[^a-z0-9_]', '_', tenantId.lower())
            partition_name = f"faq_variants_p_{sanitized_tenant}"
            
            # Check if partition exists
            partition_exists = conn.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relname = %s AND n.nspname = 'public'
                )
            """, (partition_name,)).fetchone()[0]
            
            # Check if index exists
            index_name = f"{partition_name}_embedding_idx"
            index_exists = conn.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relname = %s AND n.nspname = 'public'
                )
            """, (index_name,)).fetchone()[0]
            
            return {
                "ok": True,
                "tenant_id": tenantId,
                "partition_name": partition_name,
                "partition_exists": partition_exists,
                "index_name": index_name,
                "index_exists": index_exists,
                "message": f"Partition {partition_name} ensured (index: {index_name})"
            }
    except Exception as e:
        error_msg = str(e)
        import traceback
        traceback.print_exc()
        return {
            "ok": False,
            "error": error_msg,
            "error_type": type(e).__name__
        }


@app.post("/admin/api/db/migrate_faq_variants_to_partitioned")
async def migrate_faq_variants_to_partitioned(
    authorization: str = Header(default="")
):
    """
    Admin-only endpoint to migrate faq_variants to partitioned table faq_variants_p.
    Creates partitions for all distinct tenant_ids and copies data.
    """
    _check_admin_auth(authorization)
    
    results = {
        "migration_status": "in_progress",
        "tenants_processed": [],
        "total_rows_copied": 0,
        "errors": []
    }
    
    try:
        with get_conn() as conn:
            # Get all distinct tenant_ids from faq_variants via faq_items
            tenant_rows = conn.execute("""
                SELECT DISTINCT fi.tenant_id
                FROM faq_variants fv
                JOIN faq_items fi ON fi.id = fv.faq_id
                ORDER BY fi.tenant_id
            """).fetchall()
            
            if not tenant_rows:
                return {
                    "migration_status": "completed",
                    "message": "No data to migrate",
                    "tenants_processed": [],
                    "total_rows_copied": 0
                }
            
            total_copied = 0
            for tenant_row in tenant_rows:
                tenant_id = tenant_row[0]
                
                try:
                    # Ensure partition exists
                    conn.execute("SELECT ensure_faq_variants_partition(%s)", (tenant_id,))
                    conn.commit()
                    
                    # Count existing rows in old table for this tenant
                    old_count = conn.execute("""
                        SELECT COUNT(*)
                        FROM faq_variants fv
                        JOIN faq_items fi ON fi.id = fv.faq_id
                        WHERE fi.tenant_id = %s
                    """, (tenant_id,)).fetchone()[0]
                    
                    # Copy rows to partitioned table (with tenant_id)
                    # Note: id will be auto-generated from sequence, we don't preserve old ids
                    conn.execute("""
                        INSERT INTO faq_variants_p (tenant_id, faq_id, variant_question, variant_embedding, enabled, updated_at)
                        SELECT fi.tenant_id, fv.faq_id, fv.variant_question, fv.variant_embedding, fv.enabled, fv.updated_at
                        FROM faq_variants fv
                        JOIN faq_items fi ON fi.id = fv.faq_id
                        WHERE fi.tenant_id = %s
                    """, (tenant_id,))
                    conn.commit()
                    
                    # Verify count
                    new_count = conn.execute("""
                        SELECT COUNT(*) FROM faq_variants_p WHERE tenant_id = %s
                    """, (tenant_id,)).fetchone()[0]
                    
                    total_copied += new_count
                    results["tenants_processed"].append({
                        "tenant_id": tenant_id,
                        "old_count": old_count,
                        "new_count": new_count,
                        "status": "success"
                    })
                except Exception as e:
                    results["errors"].append({
                        "tenant_id": tenant_id,
                        "error": str(e)
                    })
                    results["tenants_processed"].append({
                        "tenant_id": tenant_id,
                        "status": "error",
                        "error": str(e)
                    })
            
            results["migration_status"] = "completed"
            results["total_rows_copied"] = total_copied
            
    except Exception as e:
        results["migration_status"] = "failed"
        results["error"] = str(e)
    
    return results


@app.get("/admin/api/vector-indexes")
def check_vector_indexes(
    authorization: str = Header(default="")
):
    """
    Admin-only endpoint to check pgvector version and indexes on faq_variants/faq_items.
    Returns pgvector version and list of indexes with their types.
    Also includes partition indexes for faq_variants_p.
    """
    _check_admin_auth(authorization)
    
    with get_conn() as conn:
        # Get pgvector version
        try:
            version_row = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
            pgvector_version = version_row[0] if version_row else "not installed"
        except Exception:
            pgvector_version = "unknown"
        
        # Get indexes on faq_variants, faq_items, and faq_variants_p partitions
        indexes = conn.execute("""
            SELECT 
                schemaname,
                tablename,
                indexname,
                indexdef
            FROM pg_indexes 
            WHERE tablename IN ('faq_variants', 'faq_items')
               OR tablename LIKE 'faq_variants_p_%'
            ORDER BY tablename, indexname
        """).fetchall()
        
        # Get partition information
        partitions = conn.execute("""
            SELECT 
                schemaname,
                tablename,
                tableowner
            FROM pg_tables
            WHERE tablename LIKE 'faq_variants_p_%'
            ORDER BY tablename
        """).fetchall()
        
        index_list = []
        for row in indexes:
            schema, table, name, definition = row
            index_type = "unknown"
            is_hnsw = "hnsw" in definition.lower()
            is_ivfflat = "ivfflat" in definition.lower()
            is_vector = "vector" in definition.lower() or "vector_cosine_ops" in definition.lower() or "vector_l2_ops" in definition.lower()
            
            if is_hnsw:
                index_type = "HNSW"
            elif is_ivfflat:
                index_type = "ivfflat"
            elif is_vector:
                index_type = "vector (unknown type)"
            else:
                index_type = "btree/hash/etc"
            
            # Extract WHERE clause if partial index
            where_clause = None
            if "WHERE" in definition.upper():
                where_start = definition.upper().find("WHERE")
                where_clause = definition[where_start:]
            
            # Extract tenant_id from partition name if applicable
            tenant_id = None
            if table.startswith("faq_variants_p_"):
                # Try to extract tenant_id from partition name
                # Partition name format: faq_variants_p_<tenant_id>
                tenant_id = table.replace("faq_variants_p_", "")
            
            index_list.append({
                "table": table,
                "name": name,
                "type": index_type,
                "definition": definition,
                "is_partial": where_clause is not None,
                "where_clause": where_clause,
                "tenant_id": tenant_id,
                "is_partition": table.startswith("faq_variants_p_")
            })
        
        partition_list = [
            {
                "name": row[1],
                "tenant_id": row[1].replace("faq_variants_p_", "") if row[1].startswith("faq_variants_p_") else None
            }
            for row in partitions
        ]
        
        return {
            "pgvector_version": pgvector_version,
            "indexes": index_list,
            "total_indexes": len(index_list),
            "partitions": partition_list,
            "total_partitions": len(partition_list)
        }


@app.post("/admin/api/tenant/{tenantId}/explain-vector-query")
async def explain_vector_query(
    tenantId: str,
    request: Request,
    authorization: str = Header(default="")
):
    """
    Admin-only endpoint to run EXPLAIN ANALYZE on the vector query.
    Returns the query plan to verify index usage.
    Uses the NEW ANN-first query structure.
    
    Optional body: {"force_index": true} to force index usage for testing.
    """
    _check_admin_auth(authorization)
    
    from pgvector.psycopg import register_vector
    from pgvector import Vector
    from app.openai_client import embed_text
    
    # Get query and force_index from request body
    force_index = False
    query_text = None
    try:
        body = await request.json()
        force_index = body.get("force_index", False)
        query_text = body.get("query")  # Get the actual query from request body
    except Exception:
        pass  # No body or invalid JSON, use defaults
    
    # Use the provided query, or fallback to a default if not provided
    if not query_text:
        query_text = "how much do you charge"  # Fallback default
    
    # Generate embedding for the actual query
    query_embedding = embed_text(query_text)
    
    if query_embedding is None:
        return {"error": f"Failed to generate embedding for query: '{query_text}'"}
    
    qv = Vector(query_embedding)
    limit = 20
    
    # Convert embedding to string for explicit casting in SQL
    embedding_str = str(list(query_embedding))
    
    with get_conn() as conn:
        register_vector(conn)
        
        # Set ivfflat.probes
        try:
            conn.execute("SET LOCAL ivfflat.probes = 10")
        except Exception:
            pass
        
        # If force_index, disable seq scan and enable index scans
        if force_index:
            try:
                conn.execute("SET LOCAL enable_seqscan = off")
                conn.execute("SET LOCAL enable_bitmapscan = on")
                conn.execute("SET LOCAL enable_indexscan = on")
            except Exception:
                pass
        
        # Run EXPLAIN ANALYZE on partitioned table query (same as production)
        # Try partitioned table first, fall back to old table if it doesn't exist
        using_partitioned = None
        try:
            plan_text = conn.execute("""
                EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
                WITH vector_candidates AS (
                    SELECT 
                        fv.id AS variant_id,
                        fv.faq_id,
                        fv.variant_question,
                        (fv.variant_embedding <=> %s::vector) AS distance
                    FROM faq_variants_p fv
                    WHERE fv.tenant_id = %s
                      AND fv.enabled = true
                    ORDER BY fv.variant_embedding <=> %s::vector
                    LIMIT %s
                )
                SELECT 
                    fi.id AS faq_id,
                    fi.question,
                    fi.answer,
                    fi.tenant_id,
                    vc.variant_question AS matched_variant,
                    (1 - vc.distance) AS score
                FROM vector_candidates vc
                JOIN faq_items fi ON fi.id = vc.faq_id
                WHERE fi.enabled = true
                  AND (fi.is_staged = false OR fi.is_staged IS NULL)
                ORDER BY vc.distance ASC
                LIMIT %s
            """, (qv, tenantId, qv, limit * 3, limit)).fetchall()
            using_partitioned = True
        except Exception as e:
            # Fallback to old table if partitioned table doesn't exist
            if "does not exist" in str(e).lower() or "relation" in str(e).lower():
                plan_text = conn.execute("""
                    EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
                    WITH vector_candidates AS (
                        SELECT 
                            fv.id AS variant_id,
                            fv.faq_id,
                            fv.variant_question,
                            (fv.variant_embedding <=> %s::vector) AS distance
                        FROM faq_variants fv
                        WHERE fv.enabled = true
                        ORDER BY fv.variant_embedding <=> %s::vector
                        LIMIT %s
                    )
                    SELECT 
                        fi.id AS faq_id,
                        fi.question,
                        fi.answer,
                        fi.tenant_id,
                        vc.variant_question AS matched_variant,
                        (1 - vc.distance) AS score
                    FROM vector_candidates vc
                    JOIN faq_items fi ON fi.id = vc.faq_id
                    WHERE fi.tenant_id = %s
                      AND fi.enabled = true
                      AND (fi.is_staged = false OR fi.is_staged IS NULL)
                    ORDER BY vc.distance ASC
                    LIMIT %s
                """, (qv, qv, limit * 10, tenantId, limit)).fetchall()
                using_partitioned = False
            else:
                raise
        
        def analyze_plan(plan_lines):
            """Helper to analyze a plan and extract index usage info."""
            uses_index = False
            index_type = None
            index_name = None
            uses_seq_scan = False
            
            for line in plan_lines:
                line_lower = line.lower()
                if "index scan" in line_lower or "bitmap index scan" in line_lower:
                    uses_index = True
                    if "hnsw" in line_lower:
                        index_type = "HNSW"
                    elif "ivfflat" in line_lower:
                        index_type = "ivfflat"
                    # Try to extract index name
                    import re
                    match = re.search(r'(\w+_embedding_\w+_idx|\w+_embedding_idx)', line, re.IGNORECASE)
                    if match:
                        index_name = match.group(1)
                elif "seq scan" in line_lower and "faq_variants" in line_lower:
                    uses_seq_scan = True
            
            if uses_index:
                status = "✅ INDEX USED"
                if index_type:
                    status += f" ({index_type})"
            elif uses_seq_scan:
                status = "❌ SEQ SCAN (index not used)"
            else:
                status = "⚠️ UNKNOWN (check plan)"
            
            return {
                "status": status,
                "uses_index": uses_index,
                "uses_seq_scan": uses_seq_scan,
                "index_type": index_type,
                "index_name": index_name
            }
        
        if plan_text:
            plan_text_lines = [row[0] for row in plan_text]
            plan_analysis = analyze_plan(plan_text_lines)
            
            result = {
                "tenant_id": tenantId,
                "query": query_text,  # The actual query used (from request body or fallback)
                "force_index": force_index,
                "using_partitioned_table": using_partitioned,
                **plan_analysis,
                "plan_text": plan_text_lines[:30],  # First 30 lines
                "plan_text_combined": "\n".join(plan_text_lines)
            }
            
            # If force_index was requested, also run normal plan for comparison
            if force_index:
                # Reset settings and run normal plan
                with get_conn() as conn_normal:
                    register_vector(conn_normal)
                    try:
                        conn_normal.execute("SET LOCAL ivfflat.probes = 10")
                    except Exception:
                        pass
                    
                    try:
                        normal_plan_text = conn_normal.execute("""
                            EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
                            WITH vector_candidates AS (
                                SELECT 
                                    fv.id AS variant_id,
                                    fv.faq_id,
                                    fv.variant_question,
                                    (fv.variant_embedding <=> %s::vector) AS distance
                                FROM faq_variants_p fv
                                WHERE fv.tenant_id = %s
                                  AND fv.enabled = true
                                ORDER BY fv.variant_embedding <=> %s::vector
                                LIMIT %s
                            )
                            SELECT 
                                fi.id AS faq_id,
                                fi.question,
                                fi.answer,
                                fi.tenant_id,
                                vc.variant_question AS matched_variant,
                                (1 - vc.distance) AS score
                            FROM vector_candidates vc
                            JOIN faq_items fi ON fi.id = vc.faq_id
                            WHERE fi.enabled = true
                              AND (fi.is_staged = false OR fi.is_staged IS NULL)
                            ORDER BY vc.distance ASC
                            LIMIT %s
                        """, (qv, tenantId, qv, limit * 3, limit)).fetchall()
                    except Exception as e:
                        # Fallback to old table
                        if "does not exist" in str(e).lower() or "relation" in str(e).lower():
                            normal_plan_text = conn_normal.execute("""
                                EXPLAIN (ANALYZE, BUFFERS, VERBOSE)
                                WITH vector_candidates AS (
                                    SELECT 
                                        fv.id AS variant_id,
                                        fv.faq_id,
                                        fv.variant_question,
                                        (fv.variant_embedding <=> %s::vector) AS distance
                                    FROM faq_variants fv
                                    WHERE fv.enabled = true
                                    ORDER BY fv.variant_embedding <=> %s::vector
                                    LIMIT %s
                                )
                                SELECT 
                                    fi.id AS faq_id,
                                    fi.question,
                                    fi.answer,
                                    fi.tenant_id,
                                    vc.variant_question AS matched_variant,
                                    (1 - vc.distance) AS score
                                FROM vector_candidates vc
                                JOIN faq_items fi ON fi.id = vc.faq_id
                                WHERE fi.tenant_id = %s
                                  AND fi.enabled = true
                                  AND (fi.is_staged = false OR fi.is_staged IS NULL)
                                ORDER BY vc.distance ASC
                                LIMIT %s
                            """, (qv, qv, limit * 10, tenantId, limit)).fetchall()
                        else:
                            raise
                    
                    if normal_plan_text:
                        normal_plan_lines = [row[0] for row in normal_plan_text]
                        normal_analysis = analyze_plan(normal_plan_lines)
                        result["normal_plan"] = {
                            **normal_analysis,
                            "plan_text": normal_plan_lines[:30]
                        }
            
            return result
        else:
            return {"error": "Failed to get EXPLAIN plan"}


@app.get("/admin/api/tenant/{tenantId}/fts-diagnostics")
def fts_diagnostics(
    tenantId: str,
    query: str,
    authorization: str = Header(default="")
):
    """
    Admin-only endpoint to diagnose FTS readiness for a tenant.
    Reports FTS statistics and runs the exact FTS query path.
    """
    _check_admin_auth(authorization)
    
    from app.fts_query_builder import build_fts_tsquery
    
    try:
        with get_conn() as conn:
            # 1. Get FAQ items count (enabled, non-staged)
            faq_items_count = conn.execute("""
                SELECT COUNT(*) 
                FROM faq_items 
                WHERE tenant_id = %s 
                  AND enabled = true 
                  AND (is_staged = false OR is_staged IS NULL)
            """, (tenantId,)).fetchone()[0]
            
            # 2. Get FAQ items with search_vector count
            faq_items_with_search_vector_count = conn.execute("""
                SELECT COUNT(*) 
                FROM faq_items 
                WHERE tenant_id = %s 
                  AND enabled = true 
                  AND (is_staged = false OR is_staged IS NULL)
                  AND search_vector IS NOT NULL 
                  AND search_vector::text != ''
            """, (tenantId,)).fetchone()[0]
            
            # 3. Get sample search_vector rows (up to 3)
            sample_rows = conn.execute("""
                SELECT id, question 
                FROM faq_items 
                WHERE tenant_id = %s 
                  AND enabled = true 
                  AND (is_staged = false OR is_staged IS NULL)
                  AND search_vector IS NOT NULL 
                  AND search_vector::text != ''
                LIMIT 3
            """, (tenantId,)).fetchall()
            
            sample_search_vector_rows = [
                {"id": int(row[0]), "question": str(row[1])}
                for row in sample_rows
            ]
            
            # 4. Build the exact same query as search_fts - use same exact logic
            # Build loose tsquery using build_fts_tsquery()
            tsq = build_fts_tsquery(query)
            
            # 5. Build tsquery strings (exact same as search_fts) - get the actual tsquery string used
            expanded_query_text = None  # Plain text after synonym expansion (for backward compat, but not used in new logic)
            tsquery_input_string = None  # The exact string passed into to_tsquery or plainto_tsquery
            tsquery_function_used = None  # "to_tsquery" or "plainto_tsquery"
            fts_query_string_used = None  # What DB executed (the actual tsquery from PostgreSQL)
            fts_matches_count = 0
            fts_top_matches = []
            
            # Use exact same logic as search_fts()
            if query.startswith("TSQUERY:"):
                # Explicit tsquery prefix - extract the actual tsquery string
                tsquery_str = query[8:].strip()
                tsquery_input_string = tsquery_str
                tsquery_function_used = "to_tsquery"
                try:
                    # Get the actual tsquery string from PostgreSQL
                    fts_query_string_used = conn.execute("""
                        SELECT to_tsquery('english', %s)::text
                    """, (tsquery_str,)).fetchone()[0]
                    
                    # Count matches using exact same WHERE filters as search_fts
                    count_rows = conn.execute("""
                        SELECT COUNT(*) 
                        FROM faq_items fi
                        WHERE fi.tenant_id = %s
                          AND fi.enabled = true
                          AND (fi.is_staged = false OR fi.is_staged IS NULL)
                          AND fi.search_vector @@ to_tsquery('english', %s)
                    """, (tenantId, tsquery_str)).fetchone()
                    fts_matches_count = count_rows[0] if count_rows else 0
                    
                    # Get top 5 matches with rank
                    top_rows = conn.execute("""
                        SELECT 
                            fi.id,
                            fi.question,
                            ts_rank_cd(ARRAY[0.1, 0.2, 0.4, 1.0], fi.search_vector, to_tsquery('english', %s)) AS fts_score
                        FROM faq_items fi
                        WHERE fi.tenant_id = %s
                          AND fi.enabled = true
                          AND (fi.is_staged = false OR fi.is_staged IS NULL)
                          AND fi.search_vector @@ to_tsquery('english', %s)
                        ORDER BY fts_score DESC
                        LIMIT 5
                    """, (tsquery_str, tenantId, tsquery_str)).fetchall()
                    
                    fts_top_matches = [
                        {
                            "id": int(row[0]),
                            "question": str(row[1]),
                            "rank_score": float(row[2])
                        }
                        for row in top_rows
                    ]
                except Exception as e:
                    # If to_tsquery fails, fts_query_string_used stays None
                    pass
            elif tsq:
                # Use to_tsquery() with our loose tsquery string
                tsquery_input_string = tsq
                tsquery_function_used = "to_tsquery"
                try:
                    # Get the actual tsquery string from PostgreSQL
                    fts_query_string_used = conn.execute("""
                        SELECT to_tsquery('english', %s)::text
                    """, (tsq,)).fetchone()[0]
                    
                    # Count matches using exact same WHERE filters as search_fts
                    count_rows = conn.execute("""
                        SELECT COUNT(*) 
                        FROM faq_items fi
                        WHERE fi.tenant_id = %s
                          AND fi.enabled = true
                          AND (fi.is_staged = false OR fi.is_staged IS NULL)
                          AND fi.search_vector @@ to_tsquery('english', %s)
                    """, (tenantId, tsq)).fetchone()
                    fts_matches_count = count_rows[0] if count_rows else 0
                    
                    # Get top 5 matches with rank
                    top_rows = conn.execute("""
                        SELECT 
                            fi.id,
                            fi.question,
                            ts_rank_cd(ARRAY[0.1, 0.2, 0.4, 1.0], fi.search_vector, to_tsquery('english', %s)) AS fts_score
                        FROM faq_items fi
                        WHERE fi.tenant_id = %s
                          AND fi.enabled = true
                          AND (fi.is_staged = false OR fi.is_staged IS NULL)
                          AND fi.search_vector @@ to_tsquery('english', %s)
                        ORDER BY fts_score DESC
                        LIMIT 5
                    """, (tsq, tenantId, tsq)).fetchall()
                    
                    fts_top_matches = [
                        {
                            "id": int(row[0]),
                            "question": str(row[1]),
                            "rank_score": float(row[2])
                        }
                        for row in top_rows
                    ]
                except Exception as e:
                    # If to_tsquery fails, fall through to plainto_tsquery path
                    tsquery_function_used = None
                    tsquery_input_string = None
                    pass
            else:
                # Fallback to plainto_tsquery() if build_fts_tsquery returned empty
                tsquery_input_string = query
                tsquery_function_used = "plainto_tsquery"
                try:
                    # Get the actual tsquery string from PostgreSQL
                    fts_query_string_used = conn.execute("""
                        SELECT plainto_tsquery('english', %s)::text
                    """, (query,)).fetchone()[0]
                    
                    # Count matches using exact same WHERE filters as search_fts
                    count_rows = conn.execute("""
                        SELECT COUNT(*) 
                        FROM faq_items fi
                        WHERE fi.tenant_id = %s
                          AND fi.enabled = true
                          AND (fi.is_staged = false OR fi.is_staged IS NULL)
                          AND fi.search_vector @@ plainto_tsquery('english', %s)
                    """, (tenantId, query)).fetchone()
                    fts_matches_count = count_rows[0] if count_rows else 0
                    
                    # Get top 5 matches with rank
                    top_rows = conn.execute("""
                        SELECT 
                            fi.id,
                            fi.question,
                            ts_rank_cd(ARRAY[0.1, 0.2, 0.4, 1.0], fi.search_vector, plainto_tsquery('english', %s)) AS fts_score
                        FROM faq_items fi
                        WHERE fi.tenant_id = %s
                          AND fi.enabled = true
                          AND (fi.is_staged = false OR fi.is_staged IS NULL)
                          AND fi.search_vector @@ plainto_tsquery('english', %s)
                        ORDER BY fts_score DESC
                        LIMIT 5
                    """, (query, tenantId, query)).fetchall()
                    
                    fts_top_matches = [
                        {
                            "id": int(row[0]),
                            "question": str(row[1]),
                            "rank_score": float(row[2])
                        }
                        for row in top_rows
                    ]
                except Exception as e:
                    # If plainto_tsquery fails, fts_query_string_used stays None
                    pass
            
            # 7. Generate notes
            notes = ""
            if faq_items_with_search_vector_count == 0:
                notes = "search_vector not built; need rebuild/backfill"
            elif faq_items_with_search_vector_count < faq_items_count:
                notes = f"Only {faq_items_with_search_vector_count}/{faq_items_count} items have search_vector; consider rebuild"
            elif fts_matches_count == 0:
                notes = f"FTS query returned 0 matches (query: '{query}', tsquery_input: '{tsquery_input_string}')"
            else:
                notes = "FTS appears healthy"
            
            return {
                "tenant_id": tenantId,
                "faq_items_count": faq_items_count,
                "faq_items_with_search_vector_count": faq_items_with_search_vector_count,
                "sample_search_vector_rows": sample_search_vector_rows,
                "expanded_query_text": expanded_query_text,  # Optional: plain text after synonym expansion (deprecated, kept for backward compat)
                "tsquery_input_string": tsquery_input_string,  # The exact string passed into to_tsquery or plainto_tsquery
                "tsquery_function_used": tsquery_function_used,  # "to_tsquery" or "plainto_tsquery"
                "fts_query_string_used": fts_query_string_used,  # What DB executed (the actual tsquery from PostgreSQL)
                "fts_matches_count": fts_matches_count,
                "fts_top_matches": fts_top_matches,
                "notes": notes
            }
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"FTS diagnostics failed: {str(e)}")


@app.post("/admin/api/tenant/{tenantId}/fts-rebuild")
def fts_rebuild(
    tenantId: str,
    authorization: str = Header(default="")
):
    """
    Admin-only endpoint to rebuild/backfill search_vector for all enabled, non-staged FAQs.
    """
    _check_admin_auth(authorization)
    
    try:
        with get_conn() as conn:
            # Update search_vector for all enabled, non-staged FAQs (weighted)
            result = conn.execute("""
                UPDATE faq_items 
                SET search_vector =
                    setweight(
                        to_tsvector(
                            'english',
                            COALESCE(question, '') || ' ' ||
                            CASE
                                WHEN faq_items.variants_json IS NULL THEN ''
                                WHEN jsonb_typeof(faq_items.variants_json) <> 'array' THEN ''
                                ELSE COALESCE((
                                    SELECT string_agg(value, ' ')
                                    FROM jsonb_array_elements_text(faq_items.variants_json)
                                ), '')
                            END
                        ),
                        'A'
                    ) ||
                    setweight(to_tsvector('english', COALESCE(answer, '')), 'C')
                WHERE tenant_id = %s 
                  AND enabled = true 
                  AND (is_staged = false OR is_staged IS NULL)
            """, (tenantId,))
            
            updated_count = result.rowcount
            conn.commit()
            
            return {
                "tenant_id": tenantId,
                "updated_rowcount": updated_count
            }
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"FTS rebuild failed: {str(e)}")


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
        result_payload = generate_quote_reply(
            req=quote_req,
            resp=resp,
            request=request
        )
        
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
            "selector_called": resp.headers.get("X-Selector-Called", "0") == "1",
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

