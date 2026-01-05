"""Clean up all FAQs and variants for a tenant."""
from app.db import get_conn

tenant_id = 'sparkys_electrical'

with get_conn() as conn:
    # Delete variants first (foreign key)
    conn.execute('''
        DELETE FROM faq_variants 
        WHERE faq_id IN (SELECT id FROM faq_items WHERE tenant_id = %s)
    ''', (tenant_id,))
    
    # Delete all FAQs (staged and live)
    deleted = conn.execute('DELETE FROM faq_items WHERE tenant_id = %s', (tenant_id,)).rowcount
    
    # Clear cache
    try:
        conn.execute('DELETE FROM retrieval_cache WHERE tenant_id = %s', (tenant_id,))
    except:
        pass
    
    conn.commit()
    print(f'Cleaned up {deleted} FAQs for {tenant_id}')

