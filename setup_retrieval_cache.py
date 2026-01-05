"""Setup retrieval cache table and variants_json column."""
from app.db import get_conn

print("Setting up retrieval infrastructure...")
print()

# 1. Create retrieval_cache table
with get_conn() as conn:
    exists = conn.execute("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_name = 'retrieval_cache'
    """).fetchone()
    
    if not exists:
        print("Creating retrieval_cache table...")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS retrieval_cache (
                cache_key VARCHAR(64) PRIMARY KEY,
                tenant_id VARCHAR(64) NOT NULL,
                result_json JSONB NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_tenant ON retrieval_cache(tenant_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_created ON retrieval_cache(created_at)")
        conn.commit()
        print("[PASS] retrieval_cache table created")
    else:
        print("[PASS] retrieval_cache table already exists")

# 2. Add variants_json column
with get_conn() as conn:
    exists = conn.execute("""
        SELECT column_name FROM information_schema.columns 
        WHERE table_name = 'faq_items' AND column_name = 'variants_json'
    """).fetchone()
    
    if not exists:
        print("Adding variants_json column...")
        conn.execute("ALTER TABLE faq_items ADD COLUMN IF NOT EXISTS variants_json JSONB DEFAULT '[]'::jsonb")
        conn.commit()
        print("[PASS] variants_json column added")
    else:
        print("[PASS] variants_json column already exists")

print()
print("Setup complete!")

