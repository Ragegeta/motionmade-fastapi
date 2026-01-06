"""Re-apply variant expansion to live FAQs."""
import sys
import json
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import get_conn
from app.variant_expander import expand_faq_list
import requests
import os

TENANT_ID = "sparkys_electrical"
ADMIN_BASE = "https://motionmade-fastapi.onrender.com"

# Load admin token
env_path = Path(__file__).parent.parent / ".env"
if not env_path.exists():
    print(f"Error: .env not found at {env_path}")
    sys.exit(1)

admin_token = None
with open(env_path) as f:
    for line in f:
        if line.startswith("ADMIN_TOKEN="):
            admin_token = line.split("=", 1)[1].strip()
            break

if not admin_token:
    print("Error: ADMIN_TOKEN not found in .env")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {admin_token}",
    "Content-Type": "application/json"
}

print(f"\n=== RE-APPLYING VARIANT EXPANSION ===")
print(f"Tenant: {TENANT_ID}\n")

# Step 1: Fetch live FAQs
print("[1/4] Fetching live FAQs...")
with get_conn() as conn:
    rows = conn.execute("""
        SELECT question, answer, variants_json 
        FROM faq_items 
        WHERE tenant_id = %s AND is_staged = false
        ORDER BY id
    """, (TENANT_ID,)).fetchall()
    
    faqs = []
    for row in rows:
        question, answer, variants_json = row
        variants = []
        if variants_json:
            try:
                variants = json.loads(variants_json)
            except:
                pass
        faqs.append({
            "question": question,
            "answer": answer,
            "variants": variants
        })

print(f"  Found {len(faqs)} live FAQs")

# Step 2: Expand variants
print("\n[2/4] Expanding variants...")
expanded_faqs = expand_faq_list(faqs, max_variants_per_faq=50)

total_before = sum(len(f.get("variants", [])) for f in faqs)
total_after = sum(len(f.get("variants", [])) for f in expanded_faqs)

print(f"  Variants: {total_before} -> {total_after}")
print(f"  Average per FAQ: {total_after / len(faqs):.1f}" if faqs else "  N/A")

# Step 3: Upload to staged
print("\n[3/4] Uploading to staged...")
staged_payload = json.dumps([{
    "question": f["question"],
    "answer": f["answer"],
    "variants": f["variants"]
} for f in expanded_faqs])

try:
    response = requests.put(
        f"{ADMIN_BASE}/admin/api/tenant/{TENANT_ID}/faqs/staged",
        headers=headers,
        data=staged_payload,
        timeout=120
    )
    response.raise_for_status()
    result = response.json()
    print(f"  Staged: {result.get('staged_count', '?')} FAQs")
except Exception as e:
    print(f"  Error: {e}")
    sys.exit(1)

# Step 4: Promote
print("\n[4/4] Promoting (triggers re-embedding)...")
try:
    response = requests.post(
        f"{ADMIN_BASE}/admin/api/tenant/{TENANT_ID}/promote",
        headers=headers,
        timeout=300
    )
    response.raise_for_status()
    result = response.json()
    print(f"  Status: {result.get('status', '?')}")
    if 'expansion_stats' in result:
        print(f"  Expansion: {result['expansion_stats']}")
except Exception as e:
    print(f"  Error: {e}")
    sys.exit(1)

print("\n✅ Complete! Waiting 30 seconds for embeddings...")
import time
time.sleep(30)

# Verify
print("\n=== VERIFICATION ===")
with get_conn() as conn:
    live_count = conn.execute(
        "SELECT COUNT(*) FROM faq_items WHERE tenant_id = %s AND is_staged = false",
        (TENANT_ID,)
    ).fetchone()[0]
    
    variant_count = conn.execute("""
        SELECT COUNT(*) FROM faq_variants fv
        JOIN faq_items fi ON fi.id = fv.faq_id
        WHERE fi.tenant_id = %s AND fi.is_staged = false
    """, (TENANT_ID,)).fetchone()[0]
    
    print(f"Live FAQs: {live_count}")
    print(f"Total variants: {variant_count}")
    if live_count > 0:
        print(f"Avg variants per FAQ: {variant_count / live_count:.1f}")

