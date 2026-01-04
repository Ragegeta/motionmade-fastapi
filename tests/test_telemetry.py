"""Test telemetry privacy and stats endpoint."""
import hashlib
import pytest
from fastapi.testclient import TestClient
from app.main import app, _hash_text
from app.db import get_conn


def test_hash_text_function():
    """Test that _hash_text generates consistent, short hashes."""
    text1 = "Hello world"
    text2 = "Hello world"
    text3 = "Different text"
    
    hash1 = _hash_text(text1)
    hash2 = _hash_text(text2)
    hash3 = _hash_text(text3)
    
    # Same text should produce same hash
    assert hash1 == hash2
    # Different text should produce different hash
    assert hash1 != hash3
    # Hash should be 16 characters (first 16 of SHA256 hex)
    assert len(hash1) == 16
    # Empty text should return empty string
    assert _hash_text("") == ""
    assert _hash_text(None) == ""


def test_telemetry_no_raw_text_stored():
    """Verify that telemetry does NOT store raw message text, only lengths and hashes."""
    client = TestClient(app)
    
    # Make a request that will trigger telemetry logging
    test_message = "This is a sensitive test message with personal info: John Doe, 123 Main St"
    response = client.post(
        "/api/v2/generate-quote-reply",
        json={
            "tenantId": "test_tenant",
            "customerMessage": test_message
        }
    )
    
    # Verify request succeeded (we don't care about the response content)
    assert response.status_code == 200
    
    # Query the telemetry table directly to verify no raw text is stored
    with get_conn() as conn:
        # First check what columns exist
        column_check = conn.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'telemetry'
        """).fetchall()
        columns = [row[0] for row in column_check]
        
        # Build query based on available columns
        has_new_columns = 'query_length' in columns and 'query_hash' in columns
        has_old_columns = 'query_text' in columns and 'normalized_text' in columns
        
        if has_new_columns:
            # New schema: check lengths and hashes
            rows = conn.execute(
                """
                SELECT query_length, normalized_length, query_hash, normalized_hash
                FROM telemetry 
                WHERE tenant_id = 'test_tenant'
                ORDER BY created_at DESC 
                LIMIT 1
                """
            ).fetchall()
            
            if rows:
                row = rows[0]
                query_len, normalized_len, query_hash, normalized_hash = row
                
                # Verify lengths are stored correctly
                assert query_len == len(test_message)
                assert normalized_len > 0
                
                # Verify hashes are stored (16-char hex strings)
                assert query_hash is not None
                assert len(query_hash) == 16
                assert normalized_hash is not None
                assert len(normalized_hash) == 16
                
                # Verify hash matches expected
                expected_hash = _hash_text(test_message)
                assert query_hash == expected_hash
                
                # CRITICAL: If old columns exist, they must be NULL or empty
                if has_old_columns:
                    old_rows = conn.execute(
                        """
                        SELECT query_text, normalized_text
                        FROM telemetry 
                        WHERE tenant_id = 'test_tenant'
                        ORDER BY created_at DESC 
                        LIMIT 1
                        """
                    ).fetchall()
                    if old_rows:
                        old_query_text, old_normalized_text = old_rows[0]
                        # Old columns should be NULL or empty (privacy violation if populated)
                        assert old_query_text is None or old_query_text == "", \
                            f"Raw query text should not be stored! Found: {old_query_text[:50]}"
                        assert old_normalized_text is None or old_normalized_text == "", \
                            f"Raw normalized text should not be stored! Found: {old_normalized_text[:50]}"
        else:
            # Schema migration hasn't happened yet - verify old columns are not populated
            # This ensures privacy even with old schema
            rows = conn.execute(
                """
                SELECT query_text, normalized_text
                FROM telemetry 
                WHERE tenant_id = 'test_tenant'
                ORDER BY created_at DESC 
                LIMIT 1
                """
            ).fetchall()
            
            if rows:
                old_query_text, old_normalized_text = rows[0]
                # CRITICAL: Old columns should be NULL or empty (privacy violation if populated)
                # Even with old schema, we should not store sensitive text
                assert old_query_text is None or old_query_text == "" or len(old_query_text) == 0, \
                    f"Raw query text should not be stored! Found: {old_query_text[:50] if old_query_text else None}"
                assert old_normalized_text is None or old_normalized_text == "" or len(old_normalized_text) == 0, \
                    f"Raw normalized text should not be stored! Found: {old_normalized_text[:50] if old_normalized_text else None}"


def test_stats_endpoint_returns_expected_keys():
    """Verify the stats endpoint returns all expected keys."""
    import os
    from app.settings import settings
    
    client = TestClient(app)
    
    # Get admin token from settings
    admin_token = settings.ADMIN_TOKEN
    
    # First, make a few requests to generate some telemetry data
    for msg in ["test query 1", "test query 2", "pets policy"]:
        client.post(
            "/api/v2/generate-quote-reply",
            json={
                "tenantId": "test_tenant",
                "customerMessage": msg
            }
        )
    
    # Call stats endpoint with proper auth
    response = client.get(
        "/admin/tenant/test_tenant/stats",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify all expected keys are present
    expected_keys = {
        "tenant_id",
        "period",
        "total_queries",
        "faq_hit_rate",
        "clarify_rate",
        "fallback_rate",
        "general_ok_rate",
        "rewrite_rate",
        "avg_latency_ms"
    }
    
    actual_keys = set(data.keys())
    assert expected_keys.issubset(actual_keys), f"Missing keys: {expected_keys - actual_keys}"
    
    # Verify data types
    assert isinstance(data["tenant_id"], str)
    assert isinstance(data["period"], str)
    assert isinstance(data["total_queries"], int)
    assert isinstance(data["faq_hit_rate"], (int, float))
    assert isinstance(data["clarify_rate"], (int, float))
    assert isinstance(data["fallback_rate"], (int, float))
    assert isinstance(data["general_ok_rate"], (int, float))
    assert isinstance(data["rewrite_rate"], (int, float))
    assert isinstance(data["avg_latency_ms"], int)
    
    # Verify rates are between 0 and 1
    assert 0 <= data["faq_hit_rate"] <= 1
    assert 0 <= data["clarify_rate"] <= 1
    assert 0 <= data["fallback_rate"] <= 1
    assert 0 <= data["general_ok_rate"] <= 1
    assert 0 <= data["rewrite_rate"] <= 1


def test_stats_endpoint_v2_returns_expected_keys():
    """Verify the API v2 stats endpoint returns all expected keys."""
    import os
    from app.settings import settings
    
    client = TestClient(app)
    
    # Get admin token from settings
    admin_token = settings.ADMIN_TOKEN
    
    # Call stats endpoint with proper auth
    response = client.get(
        "/api/v2/admin/tenant/test_tenant/stats",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify all expected keys are present (same as v1)
    expected_keys = {
        "tenant_id",
        "period",
        "total_queries",
        "faq_hit_rate",
        "clarify_rate",
        "fallback_rate",
        "general_ok_rate",
        "rewrite_rate",
        "avg_latency_ms"
    }
    
    actual_keys = set(data.keys())
    assert expected_keys.issubset(actual_keys), f"Missing keys: {expected_keys - actual_keys}"

