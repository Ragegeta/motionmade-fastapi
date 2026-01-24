"""Create ensure_faq_variants_partition function manually."""
from app.db import get_conn

FUNCTION_SQL = """
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
"""

print("Creating ensure_faq_variants_partition function...")
try:
    with get_conn() as conn:
        conn.execute(FUNCTION_SQL)
        conn.commit()
    print("✅ Function created successfully!")
except Exception as e:
    print(f"❌ Error creating function: {e}")
    raise


