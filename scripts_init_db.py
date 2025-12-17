from dotenv import load_dotenv
load_dotenv()

import os
import psycopg

db = os.environ["DATABASE_URL"]

sql = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tenants (
  id TEXT PRIMARY KEY,
  name TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Keep it simple: unique per tenant+question so admin upload can replace safely
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

-- Optional vector index (works fine with small data too)
-- You can keep it; pgvector will use it once there are enough rows.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                 WHERE c.relname='faq_items_embedding_idx' AND n.nspname='public') THEN
    EXECUTE 'CREATE INDEX faq_items_embedding_idx ON faq_items USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50)';
  END IF;
END $$;
"""

with psycopg.connect(db) as conn:
    conn.execute(sql)
    conn.commit()

print("DB schema OK")