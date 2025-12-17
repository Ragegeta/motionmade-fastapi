from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

import psycopg
from pgvector.psycopg import register_vector

from openai import OpenAI

load_dotenv()

FALLBACK = "For accurate details, please contact us directly and we’ll be happy to help."

DATABASE_URL = os.environ.get("DATABASE_URL", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-3-small")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gpt-4o-mini")
BUILD_ID = os.environ.get("BUILD_ID", "dev")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL missing in .env")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY missing in .env")
if not ADMIN_TOKEN:
    raise RuntimeError("ADMIN_TOKEN missing in .env")

client = OpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()


# ----------------------------
# Gate + safety checks
# ----------------------------
FACT_PATTERNS = [
    r"\bprice\b", r"\bcost\b", r"\bfee\b", r"\bcharge\b", r"\bhow much\b", r"\$",
    r"\baud\b",
    r"\bhow long\b", r"\bduration\b", r"\bminutes?\b", r"\bhours?\b", r"\btime\b",
    r"\binclude\b", r"\bincluded\b", r"\bwhat'?s in\b", r"\bwhat is in\b", r"\binclusions\b",
    r"\bpay\b", r"\bpayment\b", r"\binvoice\b", r"\breceipt\b", r"\bbank transfer\b", r"\bcard\b",
    r"\btravel\b", r"\bdistance\b", r"\bkm\b", r"\bsurcharge\b",
    r"\bcancel\b", r"\bcancellation\b", r"\brefund\b", r"\breschedule\b",
    r"\bavailability\b", r"\bbook\b", r"\bbooking\b", r"\bschedule\b",
]
FACT_RE = re.compile("|".join(FACT_PATTERNS), re.IGNORECASE)

# If the LLM outputs anything that looks like business facts, we hard-block it.
LLM_FACT_LEAK_RE = re.compile(
    r"(\$|aud\b|\bwe charge\b|\btravel fee\b|\bsurcharge\b|\bincludes?\b|\bincluded\b|"
    r"\bminutes?\b|\bhours?\b|\brefund\b|\bcancellation\b|\bprice\b|\bcost\b)",
    re.IGNORECASE
)


def is_fact_question(text: str) -> bool:
    return bool(FACT_RE.search(text or ""))


# ----------------------------
# DB helpers
# ----------------------------
def db_conn():
    conn = psycopg.connect(DATABASE_URL)
    register_vector(conn)
    return conn


def embed_text(text: str) -> List[float]:
    # text-embedding-3-small => 1536 dims
    r = client.embeddings.create(model=EMBED_MODEL, input=text)
    return r.data[0].embedding


def retrieve_topk(tenant_id: str, question: str, k: int = 3) -> List[Tuple[str, str, float]]:
    """
    Returns list of (faq_question, faq_answer, score) sorted best-first.
    score ~= cosine similarity (1 - cosine_distance)
    """
    v = embed_text(question)
    sql = """
      SELECT question, answer,
             1 - (embedding <=> %s) AS score
      FROM faq_items
      WHERE tenant_id = %s AND enabled = true AND embedding IS NOT NULL
      ORDER BY embedding <=> %s
      LIMIT %s;
    """
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (v, tenant_id, v, k))
            rows = cur.fetchall()
    return [(r[0], r[1], float(r[2])) for r in rows]


def ensure_tenant(conn, tenant_id: str):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;",
            (tenant_id, tenant_id),
        )


# ----------------------------
# Response shape (keep UI stable)
# ----------------------------
def make_base_payload(body: Dict[str, Any]) -> Dict[str, Any]:
    bedrooms = body.get("bedrooms")
    bathrooms = body.get("bathrooms")
    clean_type = body.get("cleanType")
    condition = body.get("condition")
    js = []
    if bedrooms is not None and bathrooms is not None and clean_type:
        js.append(f"{bedrooms} bed {bathrooms} bath {clean_type}")
    if condition:
        js.append(f"{condition} condition")
    job_summary = " ".join(js).strip()

    return {
        "mode": "info_plus_quote",
        "jobSummaryShort": job_summary,
        "lowEstimate": None,
        "highEstimate": None,
        "includedServices": [],
        "suggestedTimes": [],
        "estimateText": "",
        "disclaimer": "Prices are estimates and may vary based on condition and access.",
    }


def with_headers(resp: Response, tenant_id: str, branch: str, faq_hit: bool,
                 score: Optional[float] = None, delta: Optional[float] = None):
    resp.headers["X-Build"] = BUILD_ID
    resp.headers["X-Served-By"] = "fastapi"
    resp.headers["X-Debug-Branch"] = branch
    resp.headers["X-TenantId"] = tenant_id
    resp.headers["X-Faq-Hit"] = "true" if faq_hit else "false"
    if score is not None:
        resp.headers["X-Retrieval-Score"] = f"{score:.4f}"
    if delta is not None:
        resp.headers["X-Retrieval-Delta"] = f"{delta:.4f}"


# ----------------------------
# Routes
# ----------------------------
@app.get("/api/health")
def health():
    return PlainTextResponse("ok", headers={"X-Build": BUILD_ID, "X-Served-By": "fastapi"})


@app.put("/admin/tenant/{tenant_id}/faqs")
async def admin_put_faqs(tenant_id: str, request: Request, authorization: Optional[str] = Header(default=None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="invalid token")

    items = await request.json()
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="expected a list of {question, answer}")

    # Replace-all semantics (simple + safe)
    with db_conn() as conn:
        ensure_tenant(conn, tenant_id)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM faq_items WHERE tenant_id = %s;", (tenant_id,))
            for it in items:
                q = (it.get("question") or "").strip()
                a = (it.get("answer") or "").strip()
                if not q or not a:
                    continue
                emb = embed_text(q)
                cur.execute(
                    """
                    INSERT INTO faq_items (tenant_id, question, answer, embedding, enabled, updated_at)
                    VALUES (%s, %s, %s, %s, true, now());
                    """,
                    (tenant_id, q, a, emb),
                )

    return {"ok": True, "tenantId": tenant_id, "count": len(items)}


@app.post("/api/v2/generate-quote-reply")
async def generate_quote_reply(request: Request):
    body = await request.json()
    tenant_id = (body.get("tenantId") or "default").strip()
    customer_message = (body.get("customerMessage") or "").strip()

    payload = make_base_payload(body)

    # FACT GATE
    if is_fact_question(customer_message):
        # Vector retrieval
        results = retrieve_topk(tenant_id, customer_message, k=3)

        top1 = results[0] if len(results) >= 1 else None
        top2 = results[1] if len(results) >= 2 else None

        THETA = 0.82
        DELTA = 0.08

        if not top1:
            payload["replyText"] = FALLBACK
            resp = JSONResponse(payload)
            with_headers(resp, tenant_id, branch="fallback", faq_hit=False)
            return resp

        score1 = top1[2]
        score2 = top2[2] if top2 else 0.0
        delta = score1 - score2

        if score1 >= THETA and delta >= DELTA:
            payload["replyText"] = top1[1]  # DB answer ONLY
            resp = JSONResponse(payload)
            with_headers(resp, tenant_id, branch="fact", faq_hit=True, score=score1, delta=delta)
            return resp

        payload["replyText"] = FALLBACK
        resp = JSONResponse(payload)
        with_headers(resp, tenant_id, branch="fallback", faq_hit=False, score=score1, delta=delta)
        return resp

    # GENERAL CHAT BRANCH (GPT vibe, but hard-block business facts)
    system = (
        "Reply in one short paragraph. Do not ask follow-up questions. "
        "Do not state or imply any business facts like prices, durations, policies, inclusions, or fees. "
        f"If the user asks anything that sounds like business specifics, reply exactly: {FALLBACK}"
    )

    r = client.chat.completions.create(
        model=CHAT_MODEL,
        temperature=0.6,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": customer_message or "Hi"},
        ],
    )
    reply = (r.choices[0].message.content or "").strip()
    if not reply:
        reply = FALLBACK

    # Safety post-check
    if LLM_FACT_LEAK_RE.search(reply):
        reply = FALLBACK
        branch = "general_fallback"
    else:
        branch = "general"

    payload["replyText"] = reply
    resp = JSONResponse(payload)
    with_headers(resp, tenant_id, branch=branch, faq_hit=False)
    return resp