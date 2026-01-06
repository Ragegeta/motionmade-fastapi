"""
Smoke test to verify app.main can be imported without errors.
This ensures all dependencies are available and imports work correctly.
"""
import pytest


def test_app_main_imports_successfully():
    """Verify app.main can be imported without errors."""
    # This will fail if any imports are missing or broken
    from app.main import app
    
    assert app is not None
    assert hasattr(app, "routes")


def test_suite_runner_imports_successfully():
    """Verify suite_runner can be imported (requests dependency available)."""
    try:
        from app.suite_runner import run_suite
        assert callable(run_suite)
    except ImportError as e:
        pytest.fail(f"suite_runner import failed: {e}. Make sure 'requests' is installed.")


def test_requests_available():
    """Verify requests module is available."""
    try:
        import requests
        assert requests is not None
    except ImportError:
        pytest.fail("requests module not found. Add 'requests' to requirements.txt")


