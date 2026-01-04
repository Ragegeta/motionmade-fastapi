"""Test that debug routes endpoint is properly gated."""
import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.settings import settings


def test_debug_routes_disabled_by_default():
    """Debug endpoint must 404 when DEBUG is False."""
    # Ensure DEBUG is False
    original_debug = settings.DEBUG
    settings.DEBUG = False
    
    client = TestClient(app)
    response = client.get("/debug/routes")
    
    assert response.status_code == 404
    assert "Not found" in response.json()["detail"]
    
    # Restore original value
    settings.DEBUG = original_debug


def test_debug_routes_enabled_when_debug_true():
    """Debug endpoint returns routes when DEBUG is True."""
    # Set DEBUG to True
    original_debug = settings.DEBUG
    settings.DEBUG = True
    
    client = TestClient(app)
    response = client.get("/debug/routes")
    
    assert response.status_code == 200
    assert "routes" in response.json()
    routes = response.json()["routes"]
    assert isinstance(routes, list)
    assert len(routes) > 0
    
    # Verify we can find the admin endpoint
    admin_routes = [r for r in routes if "/admin/tenant" in r["path"]]
    assert len(admin_routes) > 0
    
    # Verify API v2 admin routes are present
    v2_admin_routes = [r for r in routes if "/api/v2/admin/tenant" in r["path"]]
    assert len(v2_admin_routes) > 0, "API v2 admin routes should be in debug output"
    
    # Restore original value
    settings.DEBUG = original_debug

