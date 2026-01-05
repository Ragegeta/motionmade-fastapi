"""
Test admin routes exist and return correct status codes.
These tests ensure routes are registered and accessible.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.settings import settings

client = TestClient(app)


def test_admin_ui_returns_200():
    """GET /admin should return 200 and HTML content."""
    response = client.get("/admin")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "admin" in response.text.lower() or "tenant" in response.text.lower()


def test_admin_api_health_returns_200():
    """GET /admin/api/health should return 200 without auth."""
    response = client.get("/admin/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "ok" in data
    assert data["ok"] is True


def test_admin_api_tenants_requires_auth():
    """GET /admin/api/tenants should return 401 without auth (not 404)."""
    response = client.get("/admin/api/tenants")
    # Should be 401 (unauthorized), not 404 (not found)
    assert response.status_code == 401


def test_admin_api_tenants_with_auth():
    """GET /admin/api/tenants should return 200 with valid token."""
    response = client.get(
        "/admin/api/tenants",
        headers={"Authorization": f"Bearer {settings.ADMIN_TOKEN}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "tenants" in data


def test_admin_api_routes_exists():
    """GET /admin/api/routes should return 401 without auth (not 404)."""
    response = client.get("/admin/api/routes")
    # Should be 401 (unauthorized), not 404 (not found)
    assert response.status_code == 401


def test_admin_api_routes_with_auth():
    """GET /admin/api/routes should return list of routes with valid token."""
    response = client.get(
        "/admin/api/routes",
        headers={"Authorization": f"Bearer {settings.ADMIN_TOKEN}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "routes" in data
    assert "total" in data
    assert isinstance(data["routes"], list)
    
    # Verify admin routes are in the list
    route_paths = [r["path"] for r in data["routes"]]
    assert "/admin" in route_paths
    assert "/admin/api/health" in route_paths
    assert "/admin/api/tenants" in route_paths

