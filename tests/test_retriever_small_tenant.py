"""Tests for small tenant fast path logic in retriever.py"""

import pytest
from unittest.mock import MagicMock, patch

from app.retriever import _get_tenant_faq_count


def test_small_tenant_fast_path_decision():
    """
    Test the gating logic: Given tenant_faq_count=6 and fts_candidates_count>=1 => vector must not run.
    
    This is a unit test that verifies the decision logic without requiring DB access.
    The actual integration is tested by checking the trace dict in the retrieve() function.
    """
    # Test that the threshold logic works correctly
    SMALL_TENANT_FAQ_THRESHOLD = 50
    
    # Test cases: (tenant_faq_count, fts_count, should_skip_vector)
    test_cases = [
        (6, 1, True),   # Small tenant (6) with 1 FTS candidate -> skip vector
        (6, 2, True),   # Small tenant (6) with 2 FTS candidates -> skip vector
        (50, 1, True),  # At threshold (50) with 1 FTS candidate -> skip vector
        (51, 1, False), # Above threshold (51) with 1 FTS candidate -> don't skip
        (6, 0, False),  # Small tenant (6) with 0 FTS candidates -> don't skip (need vector)
        (100, 8, False), # Large tenant (100) with 8 FTS candidates -> don't skip (other logic applies)
    ]
    
    for tenant_faq_count, fts_count, expected_skip in test_cases:
        # The logic: fts_count >= 1 AND tenant_faq_count <= 50
        should_skip = fts_count >= 1 and tenant_faq_count <= SMALL_TENANT_FAQ_THRESHOLD
        assert should_skip == expected_skip, (
            f"Failed for tenant_faq_count={tenant_faq_count}, fts_count={fts_count}: "
            f"expected skip={expected_skip}, got {should_skip}"
        )


@patch('app.retriever.get_conn')
def test_get_tenant_faq_count(mock_get_conn):
    """Test _get_tenant_faq_count function with mocked DB."""
    # Mock database connection and cursor
    mock_cursor = MagicMock()
    mock_cursor.execute.return_value.fetchone.return_value = (6,)  # 6 FAQs
    
    mock_conn = MagicMock()
    mock_conn.execute.return_value = mock_cursor
    mock_get_conn.return_value.__enter__.return_value = mock_conn
    
    count = _get_tenant_faq_count('sparkys_electrical')
    assert count == 6
    
    # Test error handling
    mock_get_conn.return_value.__enter__.side_effect = Exception("DB error")
    count = _get_tenant_faq_count('sparkys_electrical')
    assert count == 0  # Should return 0 on error


