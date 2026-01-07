"""
Add full-text search column to faq_items for hybrid retrieval.
"""

from app.db import get_conn


def migrate():
    with get_conn() as conn:
        # Check if column exists
        exists = conn.execute("""
            SELECT column_name FROM information_schema.columns 
            WHERE table_name = 'faq_items' AND column_name = 'search_vector'
        """).fetchone()
        
        if exists:
            print("search_vector column already exists")
            return
        
        print("Adding search_vector column...")
        
        # Add tsvector column
        conn.execute("""
            ALTER TABLE faq_items 
            ADD COLUMN search_vector tsvector
        """)
        
        # Populate it from question + answer
        conn.execute("""
            UPDATE faq_items 
            SET search_vector = to_tsvector('english', 
                COALESCE(question, '') || ' ' || COALESCE(answer, '')
            )
        """)
        
        # Create GIN index for fast search
        conn.execute("""
            CREATE INDEX idx_faq_search_vector 
            ON faq_items USING GIN(search_vector)
        """)
        
        conn.commit()
        print("Done: search_vector column added with GIN index")


def update_search_vectors(tenant_id: str = None):
    """Update search vectors for existing FAQs."""
    with get_conn() as conn:
        if tenant_id:
            conn.execute("""
                UPDATE faq_items 
                SET search_vector = to_tsvector('english', 
                    COALESCE(question, '') || ' ' || COALESCE(answer, '')
                )
                WHERE tenant_id = %s
            """, (tenant_id,))
        else:
            conn.execute("""
                UPDATE faq_items 
                SET search_vector = to_tsvector('english', 
                    COALESCE(question, '') || ' ' || COALESCE(answer, '')
                )
            """)
        conn.commit()


if __name__ == "__main__":
    migrate()


