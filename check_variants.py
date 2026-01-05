"""Check if variants_json is stored correctly."""
from app.db import get_conn
import json

tenant_id = 'sparkys_electrical'

with get_conn() as conn:
    # Check staged FAQs
    staged = conn.execute(
        'SELECT question, variants_json FROM faq_items WHERE tenant_id = %s AND is_staged = true',
        (tenant_id,)
    ).fetchall()
    
    print(f'Staged FAQs: {len(staged)}')
    for faq in staged:
        variants_json = faq[1]
        if variants_json:
            try:
                variants = json.loads(variants_json)
                print(f'  {faq[0][:40]}... variants: {len(variants)} ({variants})')
            except:
                print(f'  {faq[0][:40]}... variants_json invalid: {variants_json[:50]}')
        else:
            print(f'  {faq[0][:40]}... variants_json: NULL')
    
    # Check live FAQs and their variants
    live = conn.execute("""
        SELECT fi.question, fi.variants_json, COUNT(fv.id) as variant_count
        FROM faq_items fi
        LEFT JOIN faq_variants fv ON fv.faq_id = fi.id
        WHERE fi.tenant_id = %s AND fi.is_staged = false
        GROUP BY fi.id, fi.question, fi.variants_json
    """, (tenant_id,)).fetchall()
    
    print(f'\nLive FAQs: {len(live)}')
    for faq in live:
        variants_json = faq[1]
        variant_count = faq[2]
        print(f'  {faq[0][:40]}... {variant_count} variants in DB')
        if variants_json:
            try:
                variants = json.loads(variants_json)
                print(f'    variants_json: {len(variants)} variants ({variants})')
            except:
                print(f'    variants_json invalid: {variants_json[:50]}')

