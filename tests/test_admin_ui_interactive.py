"""
Smoke test for Admin UI interactive debugging features.
Tests that all diagnostic elements exist in the HTML.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_admin_ui_has_debug_banner():
    """Admin UI should have UI DEBUG banner with all required elements."""
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.text
    
    # Check for debug banner
    assert 'id="uiDebugBanner"' in html, "UI DEBUG banner should exist"
    assert 'id="debugTime"' in html, "Debug time element should exist"
    assert 'id="debugDomReady"' in html, "DOM ready indicator should exist"
    assert 'id="debugJsRunning"' in html, "JS running indicator should exist"
    assert 'id="debugLastClick"' in html, "Last click tracker should exist"
    assert 'id="debugTestButton"' in html, "Test button should exist"
    assert 'id="uiErrors"' in html, "Error display should exist"


def test_admin_ui_has_error_capture():
    """Admin UI should have global error capture (window.onerror)."""
    # Check that external JS file contains error capture
    response = client.get("/static/admin.js")
    assert response.status_code == 200
    js_content = response.text
    assert 'window.onerror' in js_content, "Should have window.onerror handler"
    assert 'window.onunhandledrejection' in html, "Should have unhandled rejection handler"


def test_admin_ui_has_login_button():
    """Admin UI should have login button with id."""
    response = client.get("/admin")
    html = response.text
    
    assert 'id="loginButton"' in html, "Login button should exist with id"
    assert 'id="loginDiagnostics"' in html, "Login diagnostics container should exist"


def test_admin_ui_has_copy_curl_button():
    """Admin UI should have copy curl button in banner."""
    response = client.get("/admin")
    html = response.text
    
    assert 'id="copyCurlButton"' in html, "Copy curl button should exist"


def test_admin_ui_has_domcontentloaded():
    """Admin UI should use DOMContentLoaded for initialization."""
    # Check that external JS file contains DOMContentLoaded
    response = client.get("/static/admin.js")
    assert response.status_code == 200
    js_content = response.text
    assert 'DOMContentLoaded' in js_content, "Should use DOMContentLoaded event"
    assert 'addEventListener' in html, "Should use addEventListener"

