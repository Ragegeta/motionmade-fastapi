"""Test admin debug-query endpoint to prevent regression of request parameter."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.main import app
from app.settings import settings


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_generate_quote_reply():
    """Mock generate_quote_reply to avoid calling OpenAI/DB."""
    with patch('app.main.generate_quote_reply') as mock:
        mock.return_value = {
            "replyText": "Test reply",
            "tenantId": "test_tenant"
        }
        yield mock


def test_debug_query_valid_admin_token(client, mock_generate_quote_reply):
    """Test that debug-query endpoint works with valid admin token."""
    admin_token = settings.ADMIN_TOKEN
    if not admin_token:
        pytest.skip("ADMIN_TOKEN not set in settings")
    
    response = client.post(
        "/admin/api/tenant/test_tenant/debug-query",
        json={"customerMessage": "test message"},
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "faq_hit" in data
    assert "debug_branch" in data
    assert "replyText" in data
    
    # Verify generate_quote_reply was called with correct arguments
    mock_generate_quote_reply.assert_called_once()
    call_kwargs = mock_generate_quote_reply.call_args.kwargs
    assert "req" in call_kwargs
    assert "resp" in call_kwargs
    assert "request" in call_kwargs  # This is the critical check - request must be passed


def test_debug_query_invalid_token(client):
    """Test that debug-query endpoint returns 401/403 with invalid token."""
    response = client.post(
        "/admin/api/tenant/test_tenant/debug-query",
        json={"customerMessage": "test message"},
        headers={"Authorization": "Bearer invalid_token"}
    )
    
    assert response.status_code in [401, 403]


def test_debug_query_missing_token(client):
    """Test that debug-query endpoint returns 401/403 with missing token."""
    response = client.post(
        "/admin/api/tenant/test_tenant/debug-query",
        json={"customerMessage": "test message"}
    )
    
    assert response.status_code in [401, 403]


def test_debug_query_missing_customer_message(client, mock_generate_quote_reply):
    """Test that debug-query endpoint returns 400 with missing customerMessage."""
    admin_token = settings.ADMIN_TOKEN
    if not admin_token:
        pytest.skip("ADMIN_TOKEN not set in settings")
    
    response = client.post(
        "/admin/api/tenant/test_tenant/debug-query",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    
    assert response.status_code == 400
    assert "customerMessage" in response.json()["detail"].lower()

