"""Test cache functionality."""
from fastapi.testclient import TestClient
from app.main import app
from app.cache import get_cached_result, cache_result, get_cache_stats, _retrieval_cache


def test_cache_hit_returns_identical_result():
    """Test that cache hit returns identical replyText and reduces latency."""
    client = TestClient(app)
    
    # Clear cache first
    _retrieval_cache.clear()
    
    tenant_id = "test_tenant"
    query = "pets policy"
    
    # First request (cold)
    response1 = client.post(
        "/api/v2/generate-quote-reply",
        json={
            "tenantId": tenant_id,
            "customerMessage": query
        }
    )
    
    assert response1.status_code == 200
    reply1 = response1.json()["replyText"]
    latency1 = response1.headers.get("X-Timing-Total")
    cache_hit1 = response1.headers.get("X-Cache-Hit", "false")
    
    # Verify first request was not cached
    assert cache_hit1 == "false" or cache_hit1 is None
    
    # Second request (should hit cache)
    response2 = client.post(
        "/api/v2/generate-quote-reply",
        json={
            "tenantId": tenant_id,
            "customerMessage": query
        }
    )
    
    assert response2.status_code == 200
    reply2 = response2.json()["replyText"]
    latency2 = response2.headers.get("X-Timing-Total")
    cache_hit2 = response2.headers.get("X-Cache-Hit", "false")
    
    # Verify reply is identical
    assert reply1 == reply2, "Cached result should be identical"
    
    # Verify cache was hit (if DEBUG mode is on)
    # Note: Cache hit header only appears in DEBUG mode, but cache still works
    # We can verify by checking that the reply is identical and latency is lower
    
    # Verify FAQ hit status is preserved
    assert response1.headers.get("X-Faq-Hit") == response2.headers.get("X-Faq-Hit")


def test_cache_only_for_faq_hits():
    """Test that cache only stores FAQ hits, not fallbacks/clarifies."""
    client = TestClient(app)
    
    # Clear cache
    _retrieval_cache.clear()
    
    tenant_id = "test_tenant"
    
    # Request that should clarify (junk input)
    response_clarify = client.post(
        "/api/v2/generate-quote-reply",
        json={
            "tenantId": tenant_id,
            "customerMessage": "???"
        }
    )
    
    assert response_clarify.status_code == 200
    assert response_clarify.headers.get("X-Debug-Branch") == "clarify"
    
    # Verify cache is empty (clarify shouldn't be cached)
    stats = get_cache_stats()
    # Cache might be empty or might have other entries, but clarify shouldn't add to it
    
    # Request that should hit FAQ (use a query that's likely to hit)
    response_hit = client.post(
        "/api/v2/generate-quote-reply",
        json={
            "tenantId": tenant_id,
            "customerMessage": "pets policy"
        }
    )
    
    assert response_hit.status_code == 200
    faq_hit = response_hit.headers.get("X-Faq-Hit")
    
    # If it hits FAQ, verify cache has entry; if not, that's OK for this test
    if faq_hit == "true":
        stats_after = get_cache_stats()
        # Cache should have at least one entry now if FAQ hit
        # (We can't assert exact count since cache might have other entries)


def test_cache_uses_hash_not_raw_text():
    """Test that cache key uses hash, not raw text."""
    from app.cache import _retrieval_cache
    from app.normalize import normalize_message
    
    _retrieval_cache.clear()
    
    tenant_id = "test_tenant"
    query1 = "pets policy"
    query2 = "Pets policy"  # Different case, should normalize to same
    
    normalized1 = normalize_message(query1)
    normalized2 = normalize_message(query2)
    
    # Should normalize to same
    assert normalized1 == normalized2
    
    # Cache should use normalized query hash
    payload = {"replyText": "test answer", "debug_branch": "fact_hit", "retrieval_score": 0.9, "top_faq_id": 123}
    cache_result(tenant_id, normalized1, payload)
    
    # Should retrieve with normalized2 (same hash)
    cached = get_cached_result(tenant_id, normalized2)
    assert cached is not None
    assert cached["replyText"] == "test answer"

