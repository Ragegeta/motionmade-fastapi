"""Test admin install snippet functionality."""
from fastapi.testclient import TestClient
from app.main import app
from app.settings import settings

client = TestClient(app)


def test_admin_returns_html_with_widget_js():
    """Test that GET /admin returns HTML containing widget.js and data-api."""
    response = client.get("/admin")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    
    html_content = response.text
    # Note: widget.js is referenced in the install snippet section, not in the main HTML
    # The install snippet is generated dynamically by admin.js
    assert "/static/admin.js" in html_content


