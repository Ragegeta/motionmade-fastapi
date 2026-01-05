"""Test that admin routes are accessible and properly protected."""
from fastapi.testclient import TestClient
from app.main import app
from app.settings import settings


def test_admin_faqs_route_exists_and_requires_auth():
    """Admin FAQ upload route must return 401 (not 404) when called without auth."""
    client = TestClient(app)
    
    # Test without authorization header
    response = client.put(
        "/admin/tenant/test_tenant/faqs",
        json=[{"question": "Test", "answer": "Test answer"}]
    )
    
    # Route exists, so should return 401 (Unauthorized), not 404 (Not Found)
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    assert "Unauthorized" in response.json()["detail"]


def test_admin_stats_route_exists_and_requires_auth():
    """Admin stats route must return 401 (not 404) when called without auth."""
    client = TestClient(app)
    
    # Test without authorization header
    response = client.get("/admin/tenant/test_tenant/stats")
    
    # Route exists, so should return 401 (Unauthorized), not 404 (Not Found)
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    assert "Unauthorized" in response.json()["detail"]


def test_admin_routes_in_openapi():
    """Verify admin routes are present in OpenAPI schema."""
    openapi_schema = app.openapi()
    
    assert "/admin/tenant/{tenantId}/faqs" in openapi_schema["paths"]
    assert "/admin/tenant/{tenantId}/stats" in openapi_schema["paths"]
    
    # Verify PUT method exists for FAQs
    faqs_path = openapi_schema["paths"]["/admin/tenant/{tenantId}/faqs"]
    assert "put" in faqs_path
    
    # Verify GET method exists for stats
    stats_path = openapi_schema["paths"]["/admin/tenant/{tenantId}/stats"]
    assert "get" in stats_path


def test_api_v2_admin_faqs_route_exists_and_requires_auth():
    """API v2 admin FAQ upload route must return 401 (not 404) when called without auth."""
    client = TestClient(app)
    
    # Test without authorization header
    response = client.put(
        "/api/v2/admin/tenant/test_tenant/faqs",
        json=[{"question": "Test", "answer": "Test answer"}]
    )
    
    # Route exists, so should return 401 (Unauthorized), not 404 (Not Found)
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    assert "Unauthorized" in response.json()["detail"]


def test_api_v2_admin_stats_route_exists_and_requires_auth():
    """API v2 admin stats route must return 401 (not 404) when called without auth."""
    client = TestClient(app)
    
    # Test without authorization header
    response = client.get("/api/v2/admin/tenant/test_tenant/stats")
    
    # Route exists, so should return 401 (Unauthorized), not 404 (Not Found)
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    assert "Unauthorized" in response.json()["detail"]


def test_api_v2_admin_routes_in_openapi():
    """Verify API v2 admin routes are present in OpenAPI schema."""
    openapi_schema = app.openapi()
    
    assert "/api/v2/admin/tenant/{tenantId}/faqs" in openapi_schema["paths"]
    assert "/api/v2/admin/tenant/{tenantId}/stats" in openapi_schema["paths"]
    
    # Verify PUT method exists for FAQs
    faqs_path = openapi_schema["paths"]["/api/v2/admin/tenant/{tenantId}/faqs"]
    assert "put" in faqs_path
    
    # Verify GET method exists for stats
    stats_path = openapi_schema["paths"]["/api/v2/admin/tenant/{tenantId}/stats"]
    assert "get" in stats_path

