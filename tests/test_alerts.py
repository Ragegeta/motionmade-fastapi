"""Test alerts endpoints."""
from fastapi.testclient import TestClient
from app.main import app
from app.settings import settings
from app.db import get_conn

client = TestClient(app)


def test_alerts_requires_auth():
    """Test that alerts endpoints require authentication."""
    # Test /admin/api path
    response = client.get("/admin/api/tenant/test_tenant/alerts")
    assert response.status_code == 401
    
    # Test /api/v2/admin path
    response = client.get("/api/v2/admin/tenant/test_tenant/alerts")
    assert response.status_code == 401


def test_alerts_returns_keys():
    """Test that alerts endpoint returns expected keys with valid token."""
    admin_token = settings.ADMIN_TOKEN
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Test /admin/api path
    response = client.get("/admin/api/tenant/test_tenant/alerts", headers=headers)
    assert response.status_code == 200
    data = response.json()
    
    assert "tenant_id" in data
    assert "period" in data
    assert "total_queries" in data
    assert "hit_rate" in data
    assert "fallback_rate" in data
    assert "clarify_rate" in data
    assert "error_rate" in data
    assert "avg_latency_ms" in data
    assert "alerts" in data
    assert isinstance(data["alerts"], list)
    
    # Test /api/v2/admin path
    response = client.get("/api/v2/admin/tenant/test_tenant/alerts", headers=headers)
    assert response.status_code == 200
    data2 = response.json()
    
    assert "tenant_id" in data2
    assert "alerts" in data2


