import time
from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from .settings import settings
from .models import QuoteRequest, QuoteResponse
from .guardrails import FALLBACK, is_fact_question, violates_general_safety
from .openai_client import embed_text, chat_once
from .retrieval import retrieve_faq
from .db import get_conn

app = FastAPI()

def build_id() -> str:
    if settings.BUILD_ID:
        return settings.BUILD_ID
    return time.strftime('build-%Y%m%d-%H%M%S')

GENERAL_SYSTEM = (
    'You are a helpful assistant.\\n'
    'Reply in one short paragraph.\\n'
    'Do not ask follow-up questions.\\n'
    'Do not state any prices, fees, durations, inclusions, policies, travel charges, or payment rules.\\n'
    'If the user asks for business-specific details, respond exactly with:\\n'
    f'{FALLBACK}\\n'
)

def with_headers(resp: Response, tenant_id: str, branch: str, faq_hit: bool,
                 dist: float | None = None, ddelta: float | None = None):
    resp.headers['X-Build'] = build_id()
    resp.headers['X-Served-By'] = 'fastapi'
    resp.headers['X-Debug-Branch'] = branch
    resp.headers['X-TenantId'] = tenant_id
    resp.headers['X-Faq-Hit'] = 'true' if faq_hit else 'false'
    if dist is not None:
        resp.headers['X-Retrieval-Distance'] = f'{dist:.4f}'
    if ddelta is not None:
        resp.headers['X-Retrieval-Delta'] = f'{ddelta:.4f}'

@app.get('/api/health')
def health():
    r = PlainTextResponse('ok', status_code=200)
    r.headers['X-Build'] = build_id()
    r.headers['X-Served-By'] = 'fastapi'
    return r

@app.put('/admin/tenant/{tenant_id}/faqs')
def replace_faqs(tenant_id: str, items: list[dict], authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401, detail='missing token')
    token = authorization.split(' ', 1)[1].strip()
    if token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail='bad token')

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING;', (tenant_id, tenant_id))
        conn.commit()

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM faq_items WHERE tenant_id = %s;', (tenant_id,))
            for it in items:
                q = (it.get('question') or '').strip()
                a = (it.get('answer') or '').strip()
                if not q or not a:
                    continue
                vec = embed_text(q, settings.EMBED_MODEL)
                cur.execute(
                    '''
                    INSERT INTO faq_items (tenant_id, question, answer, embedding, enabled)
                    VALUES (%s, %s, %s, %s, true);
                    ''',
                    (tenant_id, q, a, vec),
                )
        conn.commit()

    r = JSONResponse({'tenantId': tenant_id, 'count': len(items)})
    with_headers(r, tenant_id, 'admin_ok', False)
    return r

@app.post('/api/v2/generate-quote-reply')
def generate(req: QuoteRequest):
    tenant_id = req.tenantId.strip()
    question = req.customerMessage.strip()
    if not tenant_id or not question:
        r = JSONResponse(QuoteResponse(replyText=FALLBACK).model_dump())
        with_headers(r, tenant_id or 'unknown', 'bad_request', False)
        return r

    if is_fact_question(question):
        qvec = embed_text(question, settings.EMBED_MODEL)
        hit = retrieve_faq_answer(tenant_id, qvec, theta=0.18, delta=0.04)
        if hit.hit and hit.answer:
            r = JSONResponse(QuoteResponse(replyText=hit.answer).model_dump())
            with_headers(r, tenant_id, 'fact_hit', True, hit.distance, hit.delta)
            return r
        r = JSONResponse(QuoteResponse(replyText=FALLBACK).model_dump())
        with_headers(r, tenant_id, 'fact_fallback', False, hit.distance, hit.delta)
        return r

    try:
        reply = chat_once(GENERAL_SYSTEM, question, settings.CHAT_MODEL, temperature=0.6)
    except Exception:
        reply = ''

    if not reply or violates_general_safety(reply):
        r = JSONResponse(QuoteResponse(replyText=FALLBACK).model_dump())
        with_headers(r, tenant_id, 'general_fallback', False)
        return r

    r = JSONResponse(QuoteResponse(replyText=reply).model_dump())
    with_headers(r, tenant_id, 'general_ok', False)
    return r