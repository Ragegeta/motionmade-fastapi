"""Test admin-gated timing headers for /api/v2/generate-quote-reply."""
import os
from fastapi.testclient import TestClient
from app.main import app
from app.settings import settings


def test_timing_headers_absent_without_admin_token():
    """Test that timing headers are absent without admin token, even with X-Debug-Timings."""
    client = TestClient(app)
    
    response = client.post(
        "/api/v2/generate-quote-reply",
        json={
            "tenantId": "test_tenant",
            "customerMessage": "test message"
        },
        headers={
            "X-Debug-Timings": "1"
        }
    )
    
    assert response.status_code == 200
    
    # Verify timing headers are NOT present
    assert "X-Timing-Total" not in response.headers
    assert "X-Timing-Triage" not in response.headers
    assert "X-Timing-Normalize" not in response.headers
    assert "X-Timing-Embed" not in response.headers
    assert "X-Timing-Retrieval" not in response.headers
    assert "X-Timing-Rewrite" not in response.headers
    assert "X-Timing-LLM" not in response.headers
    
    # Verify gate header indicates missing auth
    assert "X-Debug-Timing-Gate" in response.headers
    assert response.headers["X-Debug-Timing-Gate"] == "missing_auth"


def test_timing_headers_present_with_admin_token():
    """Test that timing headers are present with admin token and X-Debug-Timings."""
    client = TestClient(app)
    
    admin_token = settings.ADMIN_TOKEN
    if not admin_token:
        # Skip if ADMIN_TOKEN not set
        return
    
    response = client.post(
        "/api/v2/generate-quote-reply",
        json={
            "tenantId": "test_tenant",
            "customerMessage": "test message"
        },
        headers={
            "X-Debug-Timings": "1",
            "Authorization": f"Bearer {admin_token}"
        }
    )
    
    assert response.status_code == 200
    
    # Verify gate header indicates success
    assert "X-Debug-Timing-Gate" in response.headers
    assert response.headers["X-Debug-Timing-Gate"] == "ok"
    
    # Verify timing headers ARE present
    assert "X-Timing-Total" in response.headers
    assert "X-Timing-Triage" in response.headers
    assert "X-Timing-Normalize" in response.headers
    assert "X-Timing-Embed" in response.headers
    assert "X-Timing-Retrieval" in response.headers
    assert "X-Timing-Rewrite" in response.headers
    assert "X-Timing-LLM" in response.headers
    
    # Verify values are numeric strings
    assert response.headers["X-Timing-Total"].isdigit() or (response.headers["X-Timing-Total"].startswith("-") and response.headers["X-Timing-Total"][1:].isdigit())
    assert response.headers["X-Cache-Hit"] in ["true", "false"]


def test_timing_headers_absent_without_debug_header():
    """Test that timing headers are absent without X-Debug-Timings, even with admin token."""
    client = TestClient(app)
    
    admin_token = settings.ADMIN_TOKEN
    if not admin_token:
        return
    
    response = client.post(
        "/api/v2/generate-quote-reply",
        json={
            "tenantId": "test_tenant",
            "customerMessage": "test message"
        },
        headers={
            "Authorization": f"Bearer {admin_token}"
        }
    )
    
    assert response.status_code == 200
    
    # Verify timing headers are NOT present
    assert "X-Timing-Total" not in response.headers
    assert "X-Timing-Triage" not in response.headers
    
    # Verify gate header is NOT present (only emitted when X-Debug-Timings: 1 is present)
    assert "X-Debug-Timing-Gate" not in response.headers


def test_timing_headers_absent_with_invalid_token():
    """Test that timing headers are absent with invalid admin token."""
    client = TestClient(app)
    
    response = client.post(
        "/api/v2/generate-quote-reply",
        json={
            "tenantId": "test_tenant",
            "customerMessage": "test message"
        },
        headers={
            "X-Debug-Timings": "1",
            "Authorization": "Bearer invalid_token"
        }
    )
    
    assert response.status_code == 200
    
    # Verify timing headers are NOT present
    assert "X-Timing-Total" not in response.headers
    assert "X-Timing-Triage" not in response.headers
    
    # Verify gate header indicates bad auth
    assert "X-Debug-Timing-Gate" in response.headers
    assert response.headers["X-Debug-Timing-Gate"] == "bad_auth"

