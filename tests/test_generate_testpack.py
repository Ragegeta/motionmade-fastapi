"""Unit tests for generate_testpack.py"""
import json
import tempfile
import pytest
from pathlib import Path
import sys

# Add tools directory to path so we can import generate_testpack
sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from generate_testpack import generate_testpack, generate_should_hit_queries, generate_should_miss_queries


def test_generate_testpack_structure():
    """Test that generated test pack has correct structure."""
    testpack = generate_testpack("sparkys_electrical", seed=123)
    
    # Check required keys
    assert "name" in testpack
    assert "description" in testpack
    assert "should_hit" in testpack
    assert "should_miss" in testpack
    assert "edge_unclear" in testpack
    
    # Check types
    assert isinstance(testpack["name"], str)
    assert isinstance(testpack["description"], str)
    assert isinstance(testpack["should_hit"], list)
    assert isinstance(testpack["should_miss"], list)
    assert isinstance(testpack["edge_unclear"], list)
    
    # Check all queries are strings
    for section in ["should_hit", "should_miss", "edge_unclear"]:
        for query in testpack[section]:
            assert isinstance(query, str), f"{section} contains non-string: {query}"
            assert len(query.strip()) > 0, f"{section} contains empty query"


def test_generate_testpack_total_count():
    """Test that total question count is >= 120."""
    testpack = generate_testpack("sparkys_electrical", seed=123)
    
    total = len(testpack["should_hit"]) + len(testpack["should_miss"]) + len(testpack["edge_unclear"])
    assert total >= 120, f"Total queries ({total}) should be >= 120"


def test_generate_testpack_reproducible():
    """Test that same seed produces same results."""
    pack1 = generate_testpack("sparkys_electrical", seed=123)
    pack2 = generate_testpack("sparkys_electrical", seed=123)
    
    assert pack1["should_hit"] == pack2["should_hit"]
    assert pack1["should_miss"] == pack2["should_miss"]
    assert pack1["edge_unclear"] == pack2["edge_unclear"]


def test_generate_testpack_different_seeds():
    """Test that different seeds produce valid results (may have different counts due to deduplication)."""
    pack1 = generate_testpack("sparkys_electrical", seed=123)
    pack2 = generate_testpack("sparkys_electrical", seed=456)
    
    # Should have same structure
    assert "should_hit" in pack1 and "should_hit" in pack2
    assert "should_miss" in pack1 and "should_miss" in pack2
    assert "edge_unclear" in pack1 and "edge_unclear" in pack2
    
    # Counts should be similar (within reasonable range due to deduplication)
    # Different seeds may produce slightly different counts due to deduplication
    # but should still be substantial
    assert len(pack1["should_hit"]) >= 100, "should_hit should have substantial queries"
    assert len(pack2["should_hit"]) >= 100, "should_hit should have substantial queries"
    assert len(pack1["should_miss"]) >= 50, "should_miss should have substantial queries"
    assert len(pack2["should_miss"]) >= 50, "should_miss should have substantial queries"


def test_file_write():
    """Test that test pack can be written to file and read back."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        out_path = f.name
    
    try:
        # Generate and write
        testpack = generate_testpack("test_tenant", seed=123)
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(testpack, f, indent=2, ensure_ascii=False)
        
        # Read back and verify
        with open(out_path, 'r', encoding='utf-8') as f:
            loaded = json.load(f)
        
        assert loaded["name"] == testpack["name"]
        assert loaded["description"] == testpack["description"]
        assert loaded["should_hit"] == testpack["should_hit"]
        assert loaded["should_miss"] == testpack["should_miss"]
        assert loaded["edge_unclear"] == testpack["edge_unclear"]
        
        # Verify structure matches expected format
        assert "name" in loaded
        assert "description" in loaded
        assert "should_hit" in loaded
        assert "should_miss" in loaded
        assert "edge_unclear" in loaded
        
    finally:
        # Cleanup
        Path(out_path).unlink(missing_ok=True)


def test_should_hit_contains_patterns():
    """Test that should_hit queries contain expected patterns."""
    should_hit = generate_should_hit_queries(seed=123)
    
    # Should contain short keywords
    assert any(len(q.split()) <= 3 for q in should_hit), "Should have short keyword queries"
    
    # Should contain normal sentences
    assert any(len(q.split()) > 5 for q in should_hit), "Should have normal sentence queries"
    
    # Should contain some electrical terms
    electrical_terms = ["powerpoint", "outlet", "socket", "circuit", "breaker", "smoke", "alarm", "safety", "switch"]
    found_electrical = any(term in q.lower() for q in should_hit for term in electrical_terms)
    assert found_electrical, "Should contain electrical terms"


def test_should_miss_contains_wrong_service():
    """Test that should_miss queries contain wrong-service keywords."""
    should_miss = generate_should_miss_queries(seed=123)
    
    # Should contain wrong-service terms
    wrong_service_terms = ["plumber", "toilet", "locksmith", "lock", "hvac", "air conditioner", "solar", "painter", "roofing"]
    found_wrong_service = any(term in q.lower() for q in should_miss for term in wrong_service_terms)
    assert found_wrong_service, "Should contain wrong-service terms"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

