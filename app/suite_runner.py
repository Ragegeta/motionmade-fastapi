"""
Suite runner for tenant FAQ validation.
Runs test suite against the API and returns pass/fail with first failure details.
"""
import json
import time
import requests
from typing import Dict, List, Optional, Tuple
from pathlib import Path


def load_test_suite(tenant_id: str, tests_path: Optional[Path] = None) -> List[Dict]:
    """Load test suite JSON for a tenant."""
    if tests_path is None:
        # Default to tests/{tenant_id}.json
        repo_root = Path(__file__).parent.parent
        tests_path = repo_root / "tests" / f"{tenant_id}.json"
    
    if not tests_path.exists():
        raise FileNotFoundError(f"Test suite not found: {tests_path}")
    
    with open(tests_path, "r", encoding="utf-8") as f:
        tests = json.load(f)
    
    # Handle both array format and object with 'tests' key
    if isinstance(tests, list):
        return tests
    elif isinstance(tests, dict) and "tests" in tests:
        return tests["tests"]
    else:
        raise ValueError(f"Invalid test suite format in {tests_path}")


def run_single_test(
    base_url: str,
    tenant_id: str,
    test_case: Dict,
    timeout: int = 180
) -> Dict:
    """
    Run a single test case against the API.
    
    Returns dict with:
    - passed: bool
    - test_name: str
    - input: str
    - expected: dict (expectations from test case)
    - actual: dict (actual response)
    - error: str (if any)
    """
    test_name = test_case.get("name", "unknown")
    question = test_case.get("question", "")
    
    url = f"{base_url}/api/v2/generate-quote-reply"
    payload = {
        "tenantId": tenant_id,
        "customerMessage": question
    }
    
    result = {
        "passed": False,
        "test_name": test_name,
        "input": question,
        "expected": {},
        "actual": {},
        "error": None
    }
    
    # Extract expectations
    if "expect_debug_branch_any" in test_case:
        result["expected"]["debug_branch"] = test_case["expect_debug_branch_any"]
    if "expect_faq_hit" in test_case:
        result["expected"]["faq_hit"] = test_case["expect_faq_hit"]
    if "expect_fact_gate_hit" in test_case:
        result["expected"]["fact_gate_hit"] = test_case["expect_fact_gate_hit"]
    if "min_score" in test_case:
        result["expected"]["min_score"] = test_case["min_score"]
    if "must_contain" in test_case:
        result["expected"]["must_contain"] = test_case["must_contain"]
    if "is_business_question" in test_case:
        result["expected"]["is_business_question"] = test_case["is_business_question"]
    
    try:
        response = requests.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout
        )
        
        result["actual"]["http_status"] = response.status_code
        
        if response.status_code != 200:
            result["error"] = f"HTTP {response.status_code}"
            return result
        
        # Extract headers
        headers = response.headers
        result["actual"]["debug_branch"] = headers.get("X-Debug-Branch", "")
        result["actual"]["faq_hit"] = headers.get("X-Faq-Hit", "false").lower() == "true"
        result["actual"]["fact_gate_hit"] = headers.get("X-Fact-Gate-Hit", "")
        result["actual"]["retrieval_score"] = headers.get("X-Retrieval-Score", "")
        
        # Extract body
        try:
            body = response.json()
            result["actual"]["reply_text"] = body.get("replyText", "")
        except:
            result["actual"]["reply_text"] = response.text[:200]
        
        # Validate expectations
        passed = True
        
        # Check debug branch
        if "debug_branch" in result["expected"]:
            expected_branches = result["expected"]["debug_branch"]
            if isinstance(expected_branches, str):
                expected_branches = [expected_branches]
            if result["actual"]["debug_branch"] not in expected_branches:
                passed = False
        
        # Check FAQ hit
        if "faq_hit" in result["expected"]:
            expected_hit = str(result["expected"]["faq_hit"]).lower() == "true"
            if result["actual"]["faq_hit"] != expected_hit:
                passed = False
        
        # Check fact gate hit
        if "fact_gate_hit" in result["expected"]:
            expected_gate = str(result["expected"]["fact_gate_hit"]).lower()
            actual_gate = str(result["actual"]["fact_gate_hit"]).lower()
            if actual_gate != expected_gate:
                passed = False
        
        # Check score threshold
        if "min_score" in result["expected"] and result["actual"]["retrieval_score"]:
            try:
                min_score = float(result["expected"]["min_score"])
                actual_score = float(result["actual"]["retrieval_score"])
                if actual_score < min_score:
                    passed = False
            except (ValueError, TypeError):
                pass
        
        # Check must_contain
        if "must_contain" in result["expected"]:
            reply_text = result["actual"]["reply_text"].lower()
            for token in result["expected"]["must_contain"]:
                if token.lower() not in reply_text:
                    passed = False
                    break
        
        # Business question safety check
        if result["expected"].get("is_business_question") and result["actual"]["debug_branch"] == "general_ok":
            passed = False
        
        result["passed"] = passed
        
    except requests.exceptions.Timeout:
        result["error"] = "Request timeout"
    except Exception as e:
        result["error"] = str(e)
    
    return result


def run_suite(
    base_url: str,
    tenant_id: str,
    tests_path: Optional[Path] = None,
    timeout: int = 180
) -> Dict:
    """
    Run full test suite for a tenant.
    
    Returns dict with:
    - passed: bool
    - total: int
    - passed_count: int
    - failed_count: int
    - first_failure: dict (first failing test details)
    - results: list (all test results)
    """
    try:
        tests = load_test_suite(tenant_id, tests_path)
    except Exception as e:
        return {
            "passed": False,
            "total": 0,
            "passed_count": 0,
            "failed_count": 0,
            "first_failure": {"error": f"Failed to load test suite: {str(e)}"},
            "results": []
        }
    
    results = []
    first_failure = None
    
    for test_case in tests:
        result = run_single_test(base_url, tenant_id, test_case, timeout)
        results.append(result)
        
        if not result["passed"] and first_failure is None:
            first_failure = {
                "test_name": result["test_name"],
                "input": result["input"],
                "expected": result["expected"],
                "actual": result["actual"],
                "error": result["error"]
            }
    
    passed_count = sum(1 for r in results if r["passed"])
    failed_count = len(results) - passed_count
    
    return {
        "passed": failed_count == 0,
        "total": len(results),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "first_failure": first_failure,
        "results": results
    }


