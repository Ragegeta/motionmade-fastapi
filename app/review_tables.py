"""
ReviewMate (reviews) database schema. Uses tenant_id (TEXT) to match existing tenants table.
Reversible migration: see REVIEW_SCHEMA_DOWN at bottom.
"""

# Up migration: creates all review-related tables
REVIEW_SCHEMA_SQL = """
-- OAuth state for Google OAuth flow (state -> tenant_id mapping)
CREATE TABLE IF NOT EXISTS review_oauth_states (
    state VARCHAR(64) PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_oauth_states_tenant ON review_oauth_states(tenant_id);
CREATE INDEX IF NOT EXISTS idx_review_oauth_states_created ON review_oauth_states(created_at);

-- Temporary storage after OAuth callback when user has multiple locations (pick one)
CREATE TABLE IF NOT EXISTS review_oauth_pending (
    state VARCHAR(64) PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    token_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    locations_json TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- One connection per tenant (Google Business Profile)
CREATE TABLE IF NOT EXISTS review_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    google_account_id VARCHAR(255) NOT NULL,
    google_location_id VARCHAR(255) NOT NULL,
    google_location_name VARCHAR(500),
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    token_expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_review_connections_tenant ON review_connections(tenant_id);
CREATE INDEX IF NOT EXISTS idx_review_connections_active ON review_connections(is_active);

-- Cached copy of Google reviews
CREATE TABLE IF NOT EXISTS reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES review_connections(id) ON DELETE CASCADE,
    google_review_id VARCHAR(255) NOT NULL,
    reviewer_name VARCHAR(500),
    star_rating INTEGER NOT NULL CHECK (star_rating BETWEEN 1 AND 5),
    review_text TEXT,
    review_created_at TIMESTAMP WITH TIME ZONE,
    review_updated_at TIMESTAMP WITH TIME ZONE,
    has_existing_reply BOOLEAN DEFAULT FALSE,
    existing_reply_text TEXT,
    synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_google_id ON reviews(connection_id, google_review_id);
CREATE INDEX IF NOT EXISTS idx_reviews_connection ON reviews(connection_id);
CREATE INDEX IF NOT EXISTS idx_reviews_no_reply ON reviews(connection_id, has_existing_reply) WHERE has_existing_reply = FALSE;

-- AI-generated draft responses
CREATE TABLE IF NOT EXISTS review_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id UUID NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    connection_id UUID NOT NULL REFERENCES review_connections(id) ON DELETE CASCADE,
    draft_text TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'approved', 'posted', 'rejected', 'failed')),
    edited_text TEXT,
    posted_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_review_drafts_status ON review_drafts(connection_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_review_drafts_review ON review_drafts(review_id) WHERE status != 'rejected';

-- Per-connection settings for response generation
CREATE TABLE IF NOT EXISTS review_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id UUID NOT NULL REFERENCES review_connections(id) ON DELETE CASCADE,
    business_type VARCHAR(100),
    tone VARCHAR(50) DEFAULT 'professional'
        CHECK (tone IN ('professional', 'friendly', 'casual', 'formal')),
    owner_name VARCHAR(200),
    custom_instructions TEXT,
    auto_post BOOLEAN DEFAULT FALSE,
    min_rating_for_auto INTEGER DEFAULT 4,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_review_settings_connection ON review_settings(connection_id);
"""

# Down migration (reversible) — run manually if needed
REVIEW_SCHEMA_DOWN = """
DROP TABLE IF EXISTS review_settings;
DROP TABLE IF EXISTS review_drafts;
DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS review_connections;
DROP TABLE IF EXISTS review_oauth_pending;
DROP TABLE IF EXISTS review_oauth_states;
"""


def run_review_schema(get_conn, split_schema_statements):
    """Run review schema SQL using existing get_conn and statement splitter."""
    statements = split_schema_statements(REVIEW_SCHEMA_SQL)
    for stmt in statements:
        stmt = stmt.strip()
        if not stmt or stmt.startswith("--"):
            continue
        try:
            with get_conn() as conn:
                conn.execute(stmt)
                conn.commit()
        except Exception as e:
            # Idempotent: "already exists" is fine
            if "already exists" not in str(e).lower():
                raise
