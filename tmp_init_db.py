from dotenv import load_dotenv
load_dotenv()
import os, psycopg

db = os.environ["DATABASE_URL"]

sql = """
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
    conn.execute(
        "INSERT INTO tenants (id, name) VALUES (%s, %s) "
        "ON CONFLICT (id) DO UPDATE SET name=EXCLUDED.name",
        ("motionmade", "MotionMade"),
    )
    conn.commit()

print("DB OK + tenant OK")