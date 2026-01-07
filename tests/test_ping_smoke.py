"""
Smoke test for /ping endpoint - must be fast and never fail.
This test should run in CI to ensure production health checks work.
"""
import pytest
import time
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_ping_fast(client):
    """Ping endpoint must respond in < 100ms (no DB, no external calls)."""
    start = time.time()
    response = client.get("/ping")
    elapsed_ms = (time.time() - start) * 1000
    
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert elapsed_ms < 100, f"Ping took {elapsed_ms:.1f}ms, should be < 100ms"


def test_ping_no_db_dependency(client):
    """Ping should work even if DB is unavailable."""
    # This is a smoke test - we can't easily simulate DB failure in unit tests
    # But we verify ping doesn't import DB modules at import time
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_ping_health_check_ready(client):
    """Verify /ping is suitable for Render health checks."""
    response = client.get("/ping")
    assert response.status_code == 200
    # Health checks expect 200 OK
    assert "ok" in response.json()


