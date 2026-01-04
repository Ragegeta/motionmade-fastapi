"""Test readiness endpoints."""
from fastapi.testclient import TestClient
from app.main import app
from app.settings import settings
from app.db import get_conn

client = TestClient(app)


def test_readiness_requires_auth():
    """Test that readiness endpoints require authentication."""
    # Test /admin/api path
    response = client.get("/admin/api/tenant/test_tenant/readiness")
    assert response.status_code == 401
    
    # Test /api/v2/admin path
    response = client.get("/api/v2/admin/tenant/test_tenant/readiness")
    assert response.status_code == 401


def test_readiness_returns_structure():
    """Test that readiness endpoint returns expected structure with valid token."""
    admin_token = settings.ADMIN_TOKEN
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Test /admin/api path
    response = client.get("/admin/api/tenant/test_tenant/readiness", headers=headers)
    assert response.status_code == 200
    data = response.json()
    
    assert "tenant_id" in data
    assert "ready" in data
    assert isinstance(data["ready"], bool)
    assert "checks" in data
    assert isinstance(data["checks"], list)
    assert "recommendation" in data
    
    # Verify checks structure
    for check in data["checks"]:
        assert "name" in check
        assert "passed" in check
        assert isinstance(check["passed"], bool)
        assert "message" in check
    
    # Test /api/v2/admin path
    response = client.get("/api/v2/admin/tenant/test_tenant/readiness", headers=headers)
    assert response.status_code == 200
    data2 = response.json()
    
    assert "tenant_id" in data2
    assert "ready" in data2
    assert "checks" in data2


