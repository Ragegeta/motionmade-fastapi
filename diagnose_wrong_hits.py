"""Diagnose why wrong-service queries are hitting."""
from app.db import get_conn
from app.retriever import WRONG_SERVICE_KEYWORDS

tenant_id = "brissy_cleaners"

# Check keywords
print("=== WRONG-SERVICE KEYWORDS ===")
print(f"Total keywords: {len(WRONG_SERVICE_KEYWORDS)}")
print(f"'powerpoint' in list: {'powerpoint' in WRONG_SERVICE_KEYWORDS}")
print(f"'paint' in list: {'paint' in WRONG_SERVICE_KEYWORDS}")
print(f"'painting' in list: {'painting' in WRONG_SERVICE_KEYWORDS}")
print(f"'painter' in list: {'painter' in WRONG_SERVICE_KEYWORDS}")

print("\n=== FAQ 5578 (matched by 'powerpoint' query) ===")
with get_conn() as conn:
    faq = conn.execute(
        "SELECT id, question, answer, search_vector::text FROM faq_items WHERE id=5578",
        ()
    ).fetchone()
    print(f"Q: {faq[1]}")
    print(f"A: {faq[2]}")
    print(f"\nSearch vector (first 300 chars): {faq[3][:300] if faq[3] else 'NULL'}")
    
    # Test FTS matching
    result1 = conn.execute(
        "SELECT search_vector @@ to_tsquery('english', %s) FROM faq_items WHERE id=5578",
        ("fix | powerpoint",)
    ).fetchone()
    print(f"\nDoes match 'fix | powerpoint'? {result1[0]}")
    
    result2 = conn.execute(
        "SELECT search_vector @@ to_tsquery('english', %s) FROM faq_items WHERE id=5578",
        ("fix",)
    ).fetchone()
    print(f"Does match 'fix'? {result2[0]}")

print("\n=== FAQ 5574 (matched by 'paint' query) ===")
with get_conn() as conn:
    faq = conn.execute(
        "SELECT id, question, answer, search_vector::text FROM faq_items WHERE id=5574",
        ()
    ).fetchone()
    print(f"Q: {faq[1]}")
    print(f"A: {faq[2]}")
    print(f"\nSearch vector (first 300 chars): {faq[3][:300] if faq[3] else 'NULL'}")
    
    # Test FTS matching
    result1 = conn.execute(
        "SELECT search_vector @@ to_tsquery('english', %s) FROM faq_items WHERE id=5574",
        ("paint | house",)
    ).fetchone()
    print(f"\nDoes match 'paint | house'? {result1[0]}")
    
    result2 = conn.execute(
        "SELECT search_vector @@ to_tsquery('english', %s) FROM faq_items WHERE id=5574",
        ("house",)
    ).fetchone()
    print(f"Does match 'house'? {result2[0]}")


