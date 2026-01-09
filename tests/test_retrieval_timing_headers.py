"""Test that fine-grained retrieval timing headers appear when debug timings are enabled."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.main import app
from app.settings import settings


@pytest.fixture
def client():
    return TestClient(app)


def test_retrieval_timing_headers_present_with_admin_token(client):
    """Test that fine-grained retrieval timing headers are present with admin token and X-Debug-Timings."""
    admin_token = settings.ADMIN_TOKEN
    if not admin_token:
        pytest.skip("ADMIN_TOKEN not set in settings")
    
    # Mock the retrieve function to return a trace with timing breakdowns
    mock_trace = {
        "stage": "hybrid_high_confidence",
        "retrieval_db_ms": 100,
        "retrieval_db_fts_ms": 50,
        "retrieval_db_vector_ms": 50,
        "retrieval_rerank_ms": 0,
        "retrieval_total_ms": 150,
        "candidates_count": 5,
        "cache_hit": False
    }
    
    mock_result = {
        "faq_id": 1,
        "question": "Test FAQ",
        "answer": "Test answer",
        "score": 0.8,
        "stage": "hybrid"
    }
    
    with patch('app.retriever.retrieve') as mock_retrieve:
        mock_retrieve.return_value = (mock_result, mock_trace)
        
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
        
        # Verify fine-grained retrieval timing headers are present
        assert "X-Timing-Retrieval-DB" in response.headers
        assert "X-Timing-Retrieval-FTS" in response.headers
        assert "X-Timing-Retrieval-Vector" in response.headers
        assert "X-Timing-Retrieval-Rerank" in response.headers
        
        # Verify values are numeric strings (>= 0)
        db_ms = int(response.headers["X-Timing-Retrieval-DB"])
        fts_ms = int(response.headers["X-Timing-Retrieval-FTS"])
        vector_ms = int(response.headers["X-Timing-Retrieval-Vector"])
        rerank_ms = int(response.headers["X-Timing-Retrieval-Rerank"])
        
        assert db_ms >= 0
        assert fts_ms >= 0
        assert vector_ms >= 0
        assert rerank_ms >= 0


def test_retrieval_timing_headers_absent_without_debug_header(client):
    """Test that fine-grained retrieval timing headers are absent without X-Debug-Timings."""
    admin_token = settings.ADMIN_TOKEN
    if not admin_token:
        pytest.skip("ADMIN_TOKEN not set in settings")
    
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
    
    # Verify fine-grained retrieval timing headers are NOT present
    assert "X-Timing-Retrieval-DB" not in response.headers
    assert "X-Timing-Retrieval-FTS" not in response.headers
    assert "X-Timing-Retrieval-Vector" not in response.headers
    assert "X-Timing-Retrieval-Rerank" not in response.headers

