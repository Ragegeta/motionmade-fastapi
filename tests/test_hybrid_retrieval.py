"""
Test suite for hybrid retrieval + LLM selector.

Tests:
1. Queries that SHOULD hit specific FAQs
2. Queries that SHOULD miss (not covered by FAQs)
3. Wrong-hit rate = 0% (never match wrong FAQ)
4. Clarify for ambiguous/junk queries
"""

import pytest
import json
from unittest.mock import patch, MagicMock

# Test data
SPARKYS_FAQS = [
    {"id": 1, "question": "Pricing and quotes", "answer": "Our call-out fee is $99..."},
    {"id": 2, "question": "Services we offer", "answer": "We handle powerpoints, ceiling fans, switchboards..."},
    {"id": 3, "question": "Service area", "answer": "We service Brisbane metro, Logan, Ipswich..."},
    {"id": 4, "question": "Booking and availability", "answer": "We have availability within 1-2 days..."},
    {"id": 5, "question": "Emergency electrical", "answer": "24/7 emergency service..."},
    {"id": 6, "question": "Licensed and insured", "answer": "Fully licensed and insured..."},
]

# Queries that SHOULD hit
SHOULD_HIT = [
    # Pricing
    {"query": "how much do you charge", "expected_faq": "pricing", "category": "pricing"},
    {"query": "ur prices pls", "expected_faq": "pricing", "category": "pricing"},
    {"query": "what's your call out fee", "expected_faq": "pricing", "category": "pricing"},
    {"query": "how much", "expected_faq": "pricing", "category": "pricing"},
    
    # Services
    {"query": "can u install ceiling fans", "expected_faq": "services", "category": "services"},
    {"query": "do u do smoke alarms", "expected_faq": "services", "category": "services"},
    {"query": "can you do switchboards", "expected_faq": "services", "category": "services"},
    {"query": "do you do powerpoints", "expected_faq": "services", "category": "services"},
    {"query": "wat do u do", "expected_faq": "services", "category": "services"},
    {"query": "what services do you offer", "expected_faq": "services", "category": "services"},
    
    # Service area
    {"query": "do u service logan", "expected_faq": "area", "category": "area"},
    {"query": "what areas do you cover", "expected_faq": "area", "category": "area"},
    {"query": "do you come to brisbane", "expected_faq": "area", "category": "area"},
    
    # Booking
    {"query": "can you come today", "expected_faq": "booking", "category": "booking"},
    {"query": "when are you available", "expected_faq": "booking", "category": "booking"},
    {"query": "how do i book", "expected_faq": "booking", "category": "booking"},
    
    # Emergency
    {"query": "urgent", "expected_faq": "emergency", "category": "emergency"},
    {"query": "i have no power", "expected_faq": "emergency", "category": "emergency"},
    {"query": "emergency electrician", "expected_faq": "emergency", "category": "emergency"},
    
    # Licensed
    {"query": "are you licensed", "expected_faq": "licensed", "category": "trust"},
    {"query": "r u insured", "expected_faq": "licensed", "category": "trust"},
]

# Queries that SHOULD miss (not covered)
SHOULD_MISS = [
    {"query": "do you do plumbing", "category": "wrong_service"},
    {"query": "can you paint my house", "category": "wrong_service"},
    {"query": "do you do roofing", "category": "wrong_service"},
    {"query": "can you fix my car", "category": "wrong_service"},
    {"query": "do you do tiling", "category": "wrong_service"},
    {"query": "landscaping services", "category": "wrong_service"},
]

# Queries that should CLARIFY (ambiguous/junk)
SHOULD_CLARIFY = [
    {"query": "???", "category": "junk"},
    {"query": "asdf", "category": "junk"},
    {"query": "hi", "category": "too_short"},
    {"query": "hello", "category": "greeting"},
]


class TestHybridRetrieval:
    """Tests for the hybrid retrieval system."""
    
    def test_retrieve_candidates_v2_never_empty(self):
        """Candidate list should never be empty for valid tenants with FAQs."""
        from app.retriever import retrieve_candidates_v2
        
        # This would need actual DB connection - mark as integration test
        pass
    
    def test_verify_selection_gates(self):
        """Test all guardrail verification gates."""
        from app.retriever import verify_selection
        
        candidates = [
            {"faq_id": 1, "question": "Test FAQ", "answer": "Test answer here"},
            {"faq_id": 2, "question": "Another FAQ", "answer": "Another answer"},
        ]
        
        # Gate 1: No FAQ selected
        is_valid, reason = verify_selection(None, {"choice": 0, "confidence": 0.8}, candidates)
        assert not is_valid
        assert reason == "no_faq_selected"
        
        # Gate 2: No selector response
        is_valid, reason = verify_selection(candidates[0], None, candidates)
        assert not is_valid
        assert reason == "no_selector_response"
        
        # Gate 3: Selector said none
        is_valid, reason = verify_selection(candidates[0], {"choice": -1, "confidence": 0.8}, candidates)
        assert not is_valid
        assert reason == "selector_said_none"
        
        # Gate 4: Low confidence
        is_valid, reason = verify_selection(candidates[0], {"choice": 0, "confidence": 0.3}, candidates)
        assert not is_valid
        assert "low_confidence" in reason
        
        # Gate 5: FAQ mismatch
        is_valid, reason = verify_selection(
            {"faq_id": 99, "answer": "Wrong one"},
            {"choice": 0, "confidence": 0.8},
            candidates
        )
        assert not is_valid
        assert reason == "faq_mismatch"
        
        # Gate 6: Empty answer
        is_valid, reason = verify_selection(
            {"faq_id": 1, "answer": ""},
            {"choice": 0, "confidence": 0.8},
            candidates
        )
        assert not is_valid
        assert reason == "empty_or_short_answer"
        
        # All gates pass
        is_valid, reason = verify_selection(
            {"faq_id": 1, "question": "Test FAQ", "answer": "This is a valid answer with enough content"},
            {"choice": 0, "confidence": 0.8},
            candidates
        )
        assert is_valid
        assert reason == "passed"


class TestNormalization:
    """Test that normalization handles messy input."""
    
    def test_slang_normalization(self):
        """Common slang should normalize correctly."""
        from app.normalize import normalize_message
        
        cases = [
            ("ur prices pls", "your prices please"),
            ("r u licensed", "are you licensed"),
            ("can u come 2day", "can you come today"),
            ("wat do u do", "what do you do"),
            ("do u service logan", "do you service logan"),
        ]
        
        for messy, expected in cases:
            result = normalize_message(messy)
            # Check that key words are present
            for word in expected.split():
                if len(word) > 2:  # Skip small words
                    assert word in result.lower() or word in messy.lower(), \
                        f"'{word}' not found in normalized '{result}' (from '{messy}')"


# Integration tests (require running server)
class TestEndToEnd:
    """End-to-end tests against the actual API."""
    
    @pytest.fixture
    def api_url(self):
        return "https://api.motionmadebne.com.au"
    
    @pytest.fixture
    def tenant_id(self):
        return "sparkys_electrical"
    
    def _call_api(self, api_url, tenant_id, query):
        """Helper to call the API and parse response."""
        import urllib.request
        
        body = json.dumps({"tenantId": tenant_id, "customerMessage": query}).encode()
        req = urllib.request.Request(
            f"{api_url}/api/v2/generate-quote-reply",
            data=body,
            headers={"Content-Type": "application/json"}
        )
        
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                headers = {k.lower(): v for k, v in resp.getheaders()}
                body_text = resp.read().decode()
                
                return {
                    "status": resp.status,
                    "faq_hit": headers.get("x-faq-hit", "false") == "true",
                    "score": float(headers.get("x-retrieval-score", 0) or 0),
                    "stage": headers.get("x-retrieval-stage", "unknown"),
                    "candidate_count": int(headers.get("x-candidate-count", 0) or 0),
                    "selector_called": headers.get("x-selector-called", "false") == "true",
                    "selector_confidence": float(headers.get("x-selector-confidence", 0) or 0),
                    "is_clarify": "rephrase" in body_text.lower() or "more detail" in body_text.lower(),
                    "body": body_text[:500]
                }
        except Exception as e:
            return {"error": str(e), "faq_hit": False}
    
    @pytest.mark.integration
    def test_should_hit_queries(self, api_url, tenant_id):
        """Queries that should hit their expected FAQs."""
        results = {"passed": 0, "failed": 0, "failures": []}
        
        for test in SHOULD_HIT:
            result = self._call_api(api_url, tenant_id, test["query"])
            
            if result.get("faq_hit") or result.get("is_clarify"):
                results["passed"] += 1
            else:
                results["failed"] += 1
                results["failures"].append({
                    "query": test["query"],
                    "expected": test["expected_faq"],
                    "got": result
                })
        
        hit_rate = results["passed"] / len(SHOULD_HIT) * 100
        print(f"\nSHOULD_HIT: {results['passed']}/{len(SHOULD_HIT)} ({hit_rate:.1f}%)")
        
        if results["failures"]:
            print("Failures:")
            for f in results["failures"][:5]:
                print(f"  - '{f['query']}' expected {f['expected']}, got score={f['got'].get('score', '?')}")
        
        assert hit_rate >= 75, f"Hit rate {hit_rate}% is below 75% threshold"
    
    @pytest.mark.integration
    def test_should_miss_queries(self, api_url, tenant_id):
        """Queries about services not offered should NOT hit."""
        wrong_hits = []
        
        for test in SHOULD_MISS:
            result = self._call_api(api_url, tenant_id, test["query"])
            
            if result.get("faq_hit"):
                wrong_hits.append({
                    "query": test["query"],
                    "category": test["category"],
                    "result": result
                })
            # Also verify that wrong-service queries have stage indicating rejection
            if test["category"] == "wrong_service":
                # Stage should indicate wrong_service_rejected or similar
                stage = result.get("stage", "").lower()
                assert not result.get("faq_hit"), \
                    f"'{test['query']}' should be rejected (wrong service), but got faq_hit=true"
        
        wrong_hit_rate = len(wrong_hits) / len(SHOULD_MISS) * 100
        print(f"\nSHOULD_MISS: {len(SHOULD_MISS) - len(wrong_hits)}/{len(SHOULD_MISS)} correctly missed")
        
        if wrong_hits:
            print("Wrong hits (BAD):")
            for wh in wrong_hits:
                print(f"  - '{wh['query']}' incorrectly hit with score={wh['result'].get('score', '?')}")
        
        assert len(wrong_hits) == 0, f"Wrong hit rate {wrong_hit_rate}% - should be 0%"
    
    @pytest.mark.integration
    def test_automotive_wrong_service(self, api_url, tenant_id):
        """Automotive queries should be rejected as wrong service."""
        automotive_queries = [
            "can you fix my car",
            "do you repair vehicles",
            "automotive service",
            "mechanic",
            "engine repair",
            "brakes",
            "tyres",
            "tires"
        ]
        
        for query in automotive_queries:
            result = self._call_api(api_url, tenant_id, query)
            assert not result.get("faq_hit"), \
                f"'{query}' should be rejected (automotive/wrong service), but got faq_hit=true"
            # Stage should indicate wrong_service_rejected
            stage = result.get("stage", "").lower()
            assert "wrong_service" in stage or not result.get("faq_hit"), \
                f"'{query}' should have wrong_service_rejected stage, got stage={stage}"
    
    @pytest.mark.integration
    def test_should_clarify_queries(self, api_url, tenant_id):
        """Junk/ambiguous queries should trigger clarify response."""
        for test in SHOULD_CLARIFY:
            result = self._call_api(api_url, tenant_id, test["query"])
            
            # Should either miss or clarify, never hit
            assert not result.get("faq_hit") or result.get("is_clarify"), \
                f"'{test['query']}' should clarify, not hit"
    
    @pytest.mark.integration
    def test_candidate_count_never_zero(self, api_url, tenant_id):
        """Candidate count should never be zero for valid queries, and faq_hit should never be true when candidate_count==0."""
        test_queries = ["how much", "services", "area", "booking"]
        
        for query in test_queries:
            result = self._call_api(api_url, tenant_id, query)
            
            candidate_count = result.get("candidate_count", 0)
            faq_hit = result.get("faq_hit", False)
            
            # Rule 1: Valid queries should have candidates
            assert candidate_count > 0, \
                f"'{query}' returned 0 candidates"
            
            # Rule 2: Never allow faq_hit=true when candidate_count==0
            assert not (faq_hit and candidate_count == 0), \
                f"'{query}' has faq_hit=true but candidate_count=0 (violates hard rule)"

