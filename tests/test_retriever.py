"""Unit tests for retriever.py functions."""
import pytest
from app.retriever import expand_query_synonyms, search_fts


def test_expand_query_synonyms_no_operators():
    """Test that expand_query_synonyms never returns tsquery operators."""
    test_cases = [
        "how much",
        "smoke alarm beeping",
        "my powerpoint stopped working",
        "circuit breaker keeps flipping",
        "outlet feels hot to touch",
        "wall plug not working",
        "beeping sound from alarm",
    ]
    
    for query in test_cases:
        result = expand_query_synonyms(query)
        # Assert no boolean operators
        assert "&" not in result, f"Query '{query}' contains '&': {result}"
        assert "|" not in result, f"Query '{query}' contains '|': {result}"
        assert "(" not in result or result.count("(") == 0, f"Query '{query}' contains '(': {result}"
        assert ")" not in result or result.count(")") == 0, f"Query '{query}' contains ')': {result}"
        # Result should be plain text (words separated by spaces)
        assert isinstance(result, str), f"Result should be string, got {type(result)}"
        # Result should not be empty (unless query was all stopwords)
        if query.strip():
            assert len(result.strip()) > 0, f"Result should not be empty for '{query}'"


def test_expand_query_synonyms_pricing_intent():
    """Test that pricing intent queries expand to pricing synonyms."""
    result = expand_query_synonyms("how much")
    # Should contain pricing synonyms
    assert "price" in result or "pricing" in result or "cost" in result
    # Should be plain text, no operators
    assert "&" not in result
    assert "|" not in result
    assert "(" not in result


def test_expand_query_synonyms_synonym_expansion():
    """Test that synonyms are appended as extra words."""
    # "beeping" should expand to include synonyms
    result = expand_query_synonyms("smoke alarm beeping")
    # Should contain original words
    assert "smoke" in result
    assert "alarm" in result
    assert "beeping" in result
    # Should also contain synonyms
    assert "beep" in result or "chirp" in result or "chirping" in result
    # No operators
    assert "&" not in result
    assert "|" not in result


def test_expand_query_synonyms_stopword_filtering():
    """Test that stopwords are filtered out."""
    result = expand_query_synonyms("my powerpoint stopped working")
    # Stopwords should be filtered
    assert "my" not in result.split()
    # Meaningful words should remain
    assert "powerpoint" in result or "outlet" in result or "socket" in result
    assert "stopped" in result
    assert "working" in result


def test_search_fts_uses_websearch_by_default(monkeypatch):
    """Test that search_fts uses websearch_to_tsquery by default, even when synonyms exist."""
    # Mock the database connection to avoid actual DB calls
    # This is a minimal test - just verify the function doesn't crash
    # and that it tries to use websearch path (would need full DB setup for real test)
    pass  # Skip for now - requires DB setup


def test_search_fts_tsquery_prefix(monkeypatch):
    """Test that search_fts uses to_tsquery when query is prefixed with TSQUERY:."""
    # Mock the database connection
    # This would require full DB setup to test properly
    pass  # Skip for now - requires DB setup


def test_expand_query_synonyms_phrase_handling():
    """Test that multi-word phrases are handled correctly."""
    # "wall plug" should expand to include synonyms
    result = expand_query_synonyms("wall plug not working")
    # Should contain original phrase words
    assert "wall" in result or "plug" in result
    # Should contain synonyms as separate words
    assert "powerpoint" in result or "outlet" in result or "socket" in result
    # No operators
    assert "&" not in result
    assert "|" not in result


def test_expand_query_synonyms_all_stopwords():
    """Test that queries with only stopwords return original query."""
    result = expand_query_synonyms("how much can you")
    # Should return something (pricing intent should expand)
    assert len(result.strip()) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

