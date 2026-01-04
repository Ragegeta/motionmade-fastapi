"""Smoke test for admin API flow."""
from fastapi.testclient import TestClient
from app.main import app
from app.settings import settings


def test_admin_api_flow_create_tenant_upload_stats():
    """Test the admin API flow: create tenant -> upload FAQs -> get stats."""
    client = TestClient(app)
    admin_token = settings.ADMIN_TOKEN
    
    headers = {"Authorization": f"Bearer {admin_token}"}
    test_tenant_id = "test_admin_ui_tenant"
    
    # Clean up if exists
    try:
        client.delete(f"/admin/api/tenant/{test_tenant_id}/domains/test.com", headers=headers)
    except:
        pass
    
    # 1. Create tenant
    create_res = client.post(
        "/admin/api/tenants",
        json={"id": test_tenant_id, "name": "Test Admin UI Tenant"},
        headers=headers
    )
    assert create_res.status_code == 200
    data = create_res.json()
    assert data["id"] == test_tenant_id
    assert data["created"] is True
    
    # 2. Add domain
    domain_res = client.post(
        f"/admin/api/tenant/{test_tenant_id}/domains",
        json={"domain": "test.com"},
        headers=headers
    )
    assert domain_res.status_code == 200
    assert domain_res.json()["domain"] == "test.com"
    
    # 3. Get tenant detail (verify domain was added)
    detail_res = client.get(f"/admin/api/tenant/{test_tenant_id}", headers=headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == test_tenant_id
    assert len(detail["domains"]) >= 1
    assert any(d["domain"] == "test.com" for d in detail["domains"])
    
    # 4. Upload FAQs
    faqs = [
        {
            "question": "Test Question",
            "answer": "Test Answer",
            "variants": ["test", "testing"]
        }
    ]
    upload_res = client.put(
        f"/admin/tenant/{test_tenant_id}/faqs",
        json=faqs,
        headers=headers
    )
    assert upload_res.status_code == 200
    upload_data = upload_res.json()
    assert upload_data["count"] == 1
    
    # 5. Get stats (may be empty if no queries yet)
    stats_res = client.get(f"/admin/api/tenant/{test_tenant_id}/stats", headers=headers)
    assert stats_res.status_code == 200
    stats = stats_res.json()
    assert "tenant_id" in stats
    assert "total_queries" in stats
    assert "faq_hit_rate" in stats
    assert "avg_latency_ms" in stats
    
    # 6. List tenants (verify our tenant appears)
    list_res = client.get("/admin/api/tenants", headers=headers)
    assert list_res.status_code == 200
    tenants = list_res.json()["tenants"]
    assert any(t["id"] == test_tenant_id for t in tenants)
    
    # Cleanup: remove domain
    try:
        client.delete(f"/admin/api/tenant/{test_tenant_id}/domains/test.com", headers=headers)
    except:
        pass


def test_admin_ui_page_loads():
    """Test that admin UI page loads."""
    client = TestClient(app)
    res = client.get("/admin")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    assert "Tenant Management" in res.text or "admin" in res.text.lower()

