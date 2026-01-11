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


def test_admin_faq_dump_route_exists_and_requires_auth():
    """Admin FAQ dump route must return 401 (not 404) when called without auth."""
    client = TestClient(app)
    
    # Test without authorization header
    response = client.get("/admin/api/tenant/test_tenant/faq-dump")
    
    # Route exists, so should return 401 (Unauthorized), not 404 (Not Found)
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    assert "Unauthorized" in response.json()["detail"]


def test_faq_dump_sql_parameterization():
    """
    Regression test: Verify that faq-dump endpoint SQL doesn't use % formatting that causes psycopg3 errors.
    
    This test checks that the SQL query used in the faq-dump endpoint doesn't contain
    problematic % characters that psycopg3 would interpret as placeholders.
    The test validates the SQL pattern by examining the source code structure.
    """
    import inspect
    from app.main import get_faq_dump
    
    # Get the source code of the function
    source = inspect.getsource(get_faq_dump)
    
    # Verify that the SQL query uses parameterized patterns, not ARRAY literals with %
    # The fixed version should have: priority_patterns = ['%beep%', '%chirp%', '%smoke%', '%alarm%']
    # And then use: variant_question ILIKE %s OR variant_question ILIKE %s OR ...
    assert "priority_patterns" in source, "SQL should build patterns in Python, not in SQL literals"
    assert "variant_question ILIKE %s" in source, "SQL should use parameterized ILIKE, not ARRAY['%...']"
    
    # Verify that the problematic pattern is NOT present
    problematic_pattern = "ILIKE ANY(ARRAY['%"
    assert problematic_pattern not in source, f"SQL should not contain '{problematic_pattern}' - this causes psycopg3 errors"
    
    # Verify that patterns are built in Python (not in SQL string literals)
    assert "'%beep%'" in source or '"%beep%"' in source, "Patterns should be built in Python, not in SQL"
    assert "priority_patterns[" in source, "Patterns should be accessed from Python list, not SQL array"

