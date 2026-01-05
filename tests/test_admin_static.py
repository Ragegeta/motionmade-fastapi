"""
Test that admin UI uses external JavaScript file instead of inline scripts.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_admin_contains_external_js():
    """Admin HTML should reference /static/admin.js, not contain inline script."""
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.text
    
    # Should have external script tag
    assert '/static/admin.js' in html, "Should reference /static/admin.js"
    assert 'src="/static/admin.js' in html or 'src=\"/static/admin.js' in html, "Should have src attribute"
    
    # Should NOT have inline script block (except maybe a tiny loader)
    # Count script tags - should be minimal
    script_count = html.count('<script>')
    # Allow 0 or 1 (if there's a tiny loader), but not the huge inline block
    assert script_count <= 1, f"Should have at most 1 inline script tag, found {script_count}"


def test_static_admin_js_exists():
    """Static admin.js file should be accessible and return JavaScript."""
    response = client.get("/static/admin.js")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    
    # Check Content-Type
    assert response.headers.get("Content-Type") == "application/javascript", \
        f"Expected application/javascript, got {response.headers.get('Content-Type')}"
    
    # Check Cache-Control
    assert response.headers.get("Cache-Control") == "no-store", \
        f"Expected no-store, got {response.headers.get('Cache-Control')}"
    
    # Check it's actually JavaScript
    content = response.text
    assert len(content) > 1000, "admin.js should be substantial"
    assert 'const API_BASE' in content or 'API_BASE' in content, "Should contain JavaScript code"
    assert 'function login' in content or 'login()' in content, "Should contain login function"


def test_admin_has_cache_control():
    """Admin page should have Cache-Control: no-store header."""
    response = client.get("/admin")
    assert response.status_code == 200
    assert response.headers.get("Cache-Control") == "no-store", \
        f"Expected no-store, got {response.headers.get('Cache-Control')}"

