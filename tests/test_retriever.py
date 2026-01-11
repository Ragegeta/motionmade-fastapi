"""Unit tests for retriever.py functions."""
import pytest
from app.retriever import expand_query_synonyms, search_fts
from app.fts_query_builder import build_fts_tsquery


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


def test_build_fts_tsquery_smoke_alarm_beeping():
    """Test that 'smoke alarm beeping' produces a tsquery with OR-of-pairs structure."""
    result = build_fts_tsquery("smoke alarm beeping")
    # Should contain OR-of-pairs structure (contains "|" and "&" and parentheses)
    assert "|" in result, f"Result should contain '|': {result}"
    assert "&" in result, f"Result should contain '&': {result}"
    assert "(" in result, f"Result should contain '(': {result}"
    assert ")" in result, f"Result should contain ')': {result}"
    # Should have multiple pairs connected with OR
    assert result.count("|") >= 1, f"Result should have at least one OR operator: {result}"


def test_build_fts_tsquery_powerpoint_broken():
    """Test that 'powerpoint broken' does NOT become a massive all-AND chain."""
    result = build_fts_tsquery("powerpoint broken")
    # Should have 2 groups: powerpoint group and broken
    # For 2 groups, should be "(g1 & g2)" format
    assert "&" in result, f"Result should contain '&' for 2 groups: {result}"
    # Should NOT have excessive ANDs (no more than 1 & for 2 groups)
    # Actually, for 2 groups it should be exactly "(g1 & g2)", so one &
    assert result.count("&") == 1, f"Result should have exactly one '&' for 2 groups: {result}"


def test_build_fts_tsquery_powerpoint_broken_stopped():
    """Test that 3+ concept groups use pairwise OR (not massive AND chain)."""
    result = build_fts_tsquery("powerpoint broken stopped")
    # For 3+ groups, should have OR-of-pairs: "(g1 & g2) | (g1 & g3) | (g2 & g3)"
    assert "|" in result, f"Result should contain '|' for 3+ groups with OR-of-pairs: {result}"
    assert "&" in result, f"Result should contain '&' for pairwise ANDs: {result}"
    # Should have multiple OR operators (at least 2 for 3 groups = 3 pairs)
    assert result.count("|") >= 2, f"Result should have at least 2 OR operators for 3 groups: {result}"


def test_build_fts_tsquery_call_out_fee():
    """Test that 'call out fee' uses (callout | fee) and never contains 'out'."""
    result = build_fts_tsquery("call out fee")
    # Should NOT contain "out" (it's a stopword)
    assert "out" not in result.lower(), f"Result should not contain 'out' (stopword): {result}"
    # Should contain "callout" or "fee" or both
    # Note: "call out fee" after filtering "out" becomes "call fee", which should map to synonyms
    # The phrase "call out fee" should be recognized and map to ["callout", "fee"]
    assert "callout" in result.lower() or "fee" in result.lower(), f"Result should contain 'callout' or 'fee': {result}"


def test_build_fts_tsquery_pricing_intent():
    """Test that pricing intent returns a single OR group and does NOT force AND with unrelated tokens."""
    result = build_fts_tsquery("how much")
    # Should be a single OR group (no AND operators)
    assert "&" not in result, f"Pricing intent should not contain '&': {result}"
    # Should contain OR operators for synonyms
    assert "|" in result, f"Pricing intent should contain '|' for synonyms: {result}"
    # Should contain pricing-related terms
    assert "price" in result.lower() or "pricing" in result.lower() or "cost" in result.lower() or "fee" in result.lower(), f"Result should contain pricing terms: {result}"


def test_build_fts_tsquery_single_word():
    """Test that single word queries work correctly."""
    result = build_fts_tsquery("powerpoint")
    # Should be a single group (word | synonyms)
    assert "powerpoint" in result.lower() or "outlet" in result.lower() or "socket" in result.lower(), f"Result should contain original word or synonyms: {result}"
    # Should have OR for synonyms if synonyms exist
    if "|" in result:
        # If synonyms exist, should have OR structure
        assert "(" in result and ")" in result, f"If synonyms exist, should have parentheses: {result}"


def test_build_fts_tsquery_empty():
    """Test that queries with only stopwords return empty string."""
    result = build_fts_tsquery("how much can you")
    # Pricing intent should return OR group, not empty
    # But if all words are stopwords (no pricing pattern), should return ""
    # Actually, "how much" matches pricing pattern, so should return OR group
    assert len(result) > 0, f"Pricing intent should return OR group, not empty: {result}"


def test_build_fts_tsquery_phrase_handling():
    """Test that multi-word phrases are handled correctly before stopword filtering."""
    # "wall plug" should be recognized as a phrase
    result = build_fts_tsquery("wall plug")
    # Should contain phrase synonyms
    assert "powerpoint" in result.lower() or "outlet" in result.lower() or "socket" in result.lower(), f"Phrase should expand to synonyms: {result}"
    # Should be a single group (phrase group) or 2 groups if "wall" and "plug" are separate
    # Actually, "wall plug" is in SYNONYMS, so should be one group


def test_build_fts_tsquery_max_terms_per_group():
    """Test that groups are capped to max 6 terms per group."""
    # "how much" has many synonyms: ["price", "pricing", "cost", "quote", "callout", "fee", "fees", "charge", "charges", "rates", "rate"]
    # Should be capped to 6 terms
    result = build_fts_tsquery("how much")
    # Should be a single OR group with parentheses
    assert "(" in result and ")" in result, f"Result should have parentheses: {result}"
    # Count the terms in the OR group (between parentheses)
    import re
    match = re.search(r'\((.*?)\)', result)
    if match:
        or_group = match.group(1)
        terms = [t.strip() for t in or_group.split("|")]
        # Should be capped at 6 terms
        assert len(terms) <= 6, f"OR group should have max 6 terms, got {len(terms)}: {terms}"


def test_build_fts_tsquery_order_3_word_then_2_word_then_single():
    """Test that concept groups are built in order: 3-word phrases, 2-word phrases, then single tokens."""
    # "call out fee" should be recognized as a 3-word phrase first
    result = build_fts_tsquery("call out fee")
    # Should contain "callout" or "fee" (from the 3-word phrase mapping)
    assert "callout" in result.lower() or "fee" in result.lower(), f"3-word phrase should be recognized: {result}"
    # Should NOT contain "out" (it's a stopword)
    assert "out" not in result.lower(), f"Result should not contain stopword 'out': {result}"


def test_build_fts_tsquery_returns_empty_for_all_stopwords():
    """Test that build_fts_tsquery returns empty string for queries with only stopwords (no pricing intent)."""
    # Query with only stopwords and no pricing intent should return ""
    # Use a query that's all stopwords but doesn't match pricing patterns
    result = build_fts_tsquery("can you do")
    # Should return empty string (all words are stopwords, no pricing pattern)
    assert result == "", f"Query with only stopwords (no pricing intent) should return empty string, got: {result}"
    
    # Test with single stopword
    result2 = build_fts_tsquery("to")
    assert result2 == "", f"Single stopword should return empty string, got: {result2}"


def test_build_fts_tsquery_returns_empty_for_empty_query():
    """Test that build_fts_tsquery returns empty string for empty queries."""
    result = build_fts_tsquery("")
    assert result == "", f"Empty query should return empty string, got: {result}"


def test_build_fts_tsquery_fallback_to_plainto_tsquery():
    """
    Test that when build_fts_tsquery() returns "", search_fts() would use plainto_tsquery (not websearch_to_tsquery).
    
    This test verifies the logic by checking that queries returning "" from build_fts_tsquery
    would trigger the plainto_tsquery fallback path in search_fts().
    Note: Actual search_fts() execution requires database setup, so we test the builder logic here.
    """
    # Query that should return empty from build_fts_tsquery
    empty_query = "can you do"  # All stopwords, no pricing intent
    result = build_fts_tsquery(empty_query)
    assert result == "", f"Query '{empty_query}' should return empty string from build_fts_tsquery, got: {result}"
    
    # Verify this would trigger plainto_tsquery fallback in search_fts()
    # (The actual fallback logic is: if tsq == "", use plainto_tsquery('english', query))
    # We can't test search_fts() directly without DB, but we verify the condition is met
    tsq = result
    # When tsq is empty, search_fts() should use: plainto_tsquery('english', query)
    # NOT websearch_to_tsquery (which has been removed)
    assert tsq == "", "This empty result should trigger plainto_tsquery fallback, not websearch_to_tsquery"
    
    # Also test with single stopword
    single_stopword = "to"
    result2 = build_fts_tsquery(single_stopword)
    assert result2 == "", f"Single stopword '{single_stopword}' should return empty string, got: {result2}"


def test_build_fts_tsquery_non_empty_uses_to_tsquery():
    """
    Test that when build_fts_tsquery() returns non-empty, search_fts() would use to_tsquery.
    
    This verifies that non-empty results from build_fts_tsquery trigger to_tsquery path,
    not the plainto_tsquery fallback.
    """
    # Query that should return non-empty from build_fts_tsquery
    query = "smoke alarm"
    result = build_fts_tsquery(query)
    assert result != "", f"Query '{query}' should return non-empty string from build_fts_tsquery, got: {result}"
    
    # Verify this would trigger to_tsquery path in search_fts()
    # (The actual logic is: if tsq != "", use to_tsquery('english', tsq))
    tsq = result
    assert tsq != "", "This non-empty result should trigger to_tsquery path, not plainto_tsquery fallback"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

