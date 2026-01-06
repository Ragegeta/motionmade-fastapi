"""
Import smoke test: Verify app imports without sentence-transformers installed.

This test ensures production can deploy without heavy ML dependencies.
Run with: pytest tests/test_import_smoke.py
"""
import pytest
import sys
import importlib


def test_app_imports_without_sentence_transformers():
    """Verify app.main and app.retriever import without sentence-transformers."""
    # Temporarily remove sentence-transformers if installed
    original_modules = {}
    modules_to_remove = ['sentence_transformers', 'torch', 'transformers']
    
    for mod_name in modules_to_remove:
        if mod_name in sys.modules:
            original_modules[mod_name] = sys.modules[mod_name]
            del sys.modules[mod_name]
    
    try:
        # Clear any cached imports
        importlib.invalidate_caches()
        
        # Try importing app modules
        from app.main import app
        from app.retriever import retrieve
        from app.cross_encoder import ENABLE_CROSS_ENCODER, _get_cross_encoder_model
        
        # Verify cross-encoder returns None when disabled
        model, available = _get_cross_encoder_model()
        assert model is None
        assert available is False
        
        # Verify app object exists
        assert app is not None
        
    finally:
        # Restore original modules
        for mod_name, mod in original_modules.items():
            sys.modules[mod_name] = mod
        importlib.invalidate_caches()


def test_cross_encoder_disabled_by_default():
    """Verify cross-encoder is disabled by default (no env var)."""
    import os
    # Save original value
    original = os.environ.get("ENABLE_CROSS_ENCODER")
    
    try:
        # Remove env var to test default
        if "ENABLE_CROSS_ENCODER" in os.environ:
            del os.environ["ENABLE_CROSS_ENCODER"]
        
        # Reload module to pick up default
        import importlib
        import app.cross_encoder
        importlib.reload(app.cross_encoder)
        
        # Check default is False
        assert app.cross_encoder.ENABLE_CROSS_ENCODER is False
        
        # Verify model returns None
        model, available = app.cross_encoder._get_cross_encoder_model()
        assert model is None
        assert available is False
        
    finally:
        # Restore original
        if original is not None:
            os.environ["ENABLE_CROSS_ENCODER"] = original
        elif "ENABLE_CROSS_ENCODER" in os.environ:
            del os.environ["ENABLE_CROSS_ENCODER"]
        
        # Reload module
        import importlib
        import app.cross_encoder
        importlib.reload(app.cross_encoder)


def test_ping_imports_fast():
    """Verify /ping endpoint imports without heavy dependencies."""
    from fastapi.testclient import TestClient
    from app.main import app
    
    client = TestClient(app)
    response = client.get("/ping")
    
    assert response.status_code == 200
    assert response.json() == {"ok": True}
