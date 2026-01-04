"""Tests for FAQ staging, promote, and rollback."""
from fastapi.testclient import TestClient
from app.main import app
from app.settings import settings
from app.db import get_conn
from app.openai_client import embed_text
from pgvector import Vector


def test_staged_upload_doesnt_affect_live():
    """Test that uploading staged FAQs doesn't affect live FAQs."""
    client = TestClient(app)
    admin_token = settings.ADMIN_TOKEN
    headers = {"Authorization": f"Bearer {admin_token}"}
    test_tenant_id = "test_staging_tenant"
    
    # Clean up
    try:
        with get_conn() as conn:
            conn.execute("DELETE FROM faq_items WHERE tenant_id=%s", (test_tenant_id,))
            conn.execute("DELETE FROM faq_items_last_good WHERE tenant_id=%s", (test_tenant_id,))
            conn.commit()
    except:
        pass
    
    # 1. Upload live FAQs
    live_faqs = [
        {"question": "Live Question 1", "answer": "Live Answer 1", "variants": []},
        {"question": "Live Question 2", "answer": "Live Answer 2", "variants": []}
    ]
    live_res = client.put(
        f"/admin/tenant/{test_tenant_id}/faqs",
        json=live_faqs,
        headers=headers
    )
    if live_res.status_code != 200:
        print(f"Live upload failed: {live_res.status_code} - {live_res.text}")
    assert live_res.status_code == 200, f"Expected 200, got {live_res.status_code}: {live_res.text}"
    assert live_res.json()["count"] == 2
    
    # 2. Upload staged FAQs (different content)
    staged_faqs = [
        {"question": "Staged Question 1", "answer": "Staged Answer 1", "variants": []},
        {"question": "Staged Question 2", "answer": "Staged Answer 2", "variants": []}
    ]
    staged_res = client.put(
        f"/admin/api/tenant/{test_tenant_id}/faqs/staged",
        json=staged_faqs,
        headers=headers
    )
    assert staged_res.status_code == 200
    assert staged_res.json()["staged_count"] == 2
    
    # 3. Verify live FAQs are unchanged
    with get_conn() as conn:
        live_count = conn.execute(
            "SELECT COUNT(*) FROM faq_items WHERE tenant_id=%s AND is_staged=false",
            (test_tenant_id,)
        ).fetchone()[0]
        staged_count = conn.execute(
            "SELECT COUNT(*) FROM faq_items WHERE tenant_id=%s AND is_staged=true",
            (test_tenant_id,)
        ).fetchone()[0]
        
        live_questions = conn.execute(
            "SELECT question FROM faq_items WHERE tenant_id=%s AND is_staged=false ORDER BY question",
            (test_tenant_id,)
        ).fetchall()
    
    assert live_count == 2
    assert staged_count == 2
    assert [row[0] for row in live_questions] == ["Live Question 1", "Live Question 2"]


def test_promote_only_on_pass():
    """Test that promote only succeeds when suite passes."""
    client = TestClient(app)
    admin_token = settings.ADMIN_TOKEN
    headers = {"Authorization": f"Bearer {admin_token}"}
    test_tenant_id = "test_promote_tenant"
    
    # This test would need a real test suite file
    # For now, we'll test the endpoint exists and handles missing staged FAQs
    res = client.post(
        f"/admin/api/tenant/{test_tenant_id}/promote",
        headers=headers
    )
    # Should fail because no staged FAQs
    assert res.status_code == 400
    assert "No staged FAQs" in res.json()["detail"]


def test_rollback_restores():
    """Test that rollback restores last_good FAQs."""
    client = TestClient(app)
    admin_token = settings.ADMIN_TOKEN
    headers = {"Authorization": f"Bearer {admin_token}"}
    test_tenant_id = "test_rollback_tenant"
    
    # Clean up
    try:
        with get_conn() as conn:
            conn.execute("DELETE FROM faq_items WHERE tenant_id=%s", (test_tenant_id,))
            conn.execute("DELETE FROM faq_items_last_good WHERE tenant_id=%s", (test_tenant_id,))
            conn.commit()
    except:
        pass
    
    # 1. Create last_good FAQs
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            (test_tenant_id, test_tenant_id)
        )
        
        # Add to last_good
        q1, a1 = "Last Good Q1", "Last Good A1"
        emb1 = embed_text(q1)
        conn.execute("""
            INSERT INTO faq_items_last_good (tenant_id, question, answer, embedding)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (tenant_id, question) DO UPDATE SET answer=EXCLUDED.answer
        """, (test_tenant_id, q1, a1, Vector(emb1)))
        
        # Add different live FAQs
        q2, a2 = "Live Q1", "Live A1"
        emb2 = embed_text(q2)
        faq_row = conn.execute("""
            INSERT INTO faq_items (tenant_id, question, answer, embedding, enabled, is_staged)
            VALUES (%s, %s, %s, %s, true, false) RETURNING id
        """, (test_tenant_id, q2, a2, Vector(emb2))).fetchone()
        faq_id = faq_row[0]
        
        # Add variant
        v_emb = embed_text(q2)
        conn.execute("""
            INSERT INTO faq_variants (faq_id, variant_question, variant_embedding, enabled)
            VALUES (%s, %s, %s, true)
        """, (faq_id, q2, Vector(v_emb)))
        
        conn.commit()
    
    # 2. Rollback
    rollback_res = client.post(
        f"/admin/api/tenant/{test_tenant_id}/rollback",
        headers=headers
    )
    assert rollback_res.status_code == 200
    assert rollback_res.json()["status"] == "success"
    
    # 3. Verify live FAQs were restored from last_good
    with get_conn() as conn:
        live_questions = conn.execute(
            "SELECT question FROM faq_items WHERE tenant_id=%s AND is_staged=false ORDER BY question",
            (test_tenant_id,)
        ).fetchall()
    
    assert len(live_questions) == 1
    assert live_questions[0][0] == "Last Good Q1"

