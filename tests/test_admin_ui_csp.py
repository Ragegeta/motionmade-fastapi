"""
Test Admin UI CSP compliance - no inline onclick handlers.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_admin_ui_returns_html():
    """GET /admin should return HTML."""
    response = client.get("/admin")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    html = response.text


def test_admin_ui_has_login_elements():
    """Admin UI should contain login form elements."""
    response = client.get("/admin")
    html = response.text
    
    assert 'id="adminToken"' in html, "Login input should exist"
    assert 'id="loginButton"' in html, "Login button should exist"
    assert 'id="authSection"' in html, "Auth section should exist"


def test_admin_ui_no_inline_onclick_on_login_button():
    """Login button should NOT have inline onclick attribute."""
    response = client.get("/admin")
    html = response.text
    
    # Check that login button doesn't have onclick
    # Find the login button line
    lines = html.split('\n')
    login_button_line = None
    for i, line in enumerate(lines):
        if 'id="loginButton"' in line or ('Login</button>' in line and 'loginButton' in html):
            # Check surrounding lines for onclick
            for check_line in lines[max(0, i-2):i+2]:
                if 'id="loginButton"' in check_line or 'Login</button>' in check_line:
                    login_button_line = check_line
                    break
            break
    
    if login_button_line:
        assert 'onclick=' not in login_button_line.lower(), \
            f"Login button should not have onclick attribute. Found: {login_button_line[:100]}"
    
    # Also check that there's no onclick="login()" anywhere near the login button
    # Get the section with login button
    auth_section_start = html.find('id="authSection"')
    if auth_section_start != -1:
        auth_section_end = html.find('</div>', auth_section_start)
        if auth_section_end != -1:
            auth_section = html[auth_section_start:auth_section_end]
            # Login button should not have onclick in this section
            if 'id="loginButton"' in auth_section:
                assert 'onclick="login()"' not in auth_section, \
                    "Login button should not have onclick=\"login()\" attribute"


def test_admin_ui_uses_event_listeners():
    """Admin UI should use addEventListener (DOMContentLoaded)."""
    response = client.get("/admin")
    html = response.text
    
    assert 'addEventListener' in html, "Should use addEventListener for event binding"
    assert 'DOMContentLoaded' in html, "Should wait for DOMContentLoaded before binding events"


def test_admin_ui_has_login_function():
    """Admin UI should have login() function defined."""
    response = client.get("/admin")
    html = response.text
    
    assert 'function login()' in html, "login() function should be defined"
    assert 'adminToken' in html, "Should use adminToken variable"


def test_admin_ui_has_diagnostic_banner():
    """Admin UI should have diagnostic banner container."""
    response = client.get("/admin")
    html = response.text
    
    assert 'id="diagnosticBanner"' in html, "Diagnostic banner should exist"
    assert 'id="jsStatus"' in html, "JS status element should exist"
    assert 'id="apiBaseDisplay"' in html, "API base display should exist"
    assert 'id="healthStatus"' in html, "Health status element should exist"
    assert 'id="gitShaDisplay"' in html, "Git SHA display should exist"


def test_admin_ui_has_login_button_id():
    """Admin UI should have loginButton with id (not onclick)."""
    response = client.get("/admin")
    html = response.text
    
    assert 'id="loginButton"' in html, "Login button should have id"
    assert 'id="copyCurlButton"' in html, "Copy curl button should exist"
    assert 'id="loginDiagnostics"' in html, "Login diagnostics container should exist"

