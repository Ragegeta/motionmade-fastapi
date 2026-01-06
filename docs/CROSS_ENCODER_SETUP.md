# Cross-Encoder Setup Guide

## Overview

The cross-encoder reranking is **optional** and disabled by default to keep production deploys fast.

**Default behavior:**
- Cross-encoder is **disabled** (`ENABLE_CROSS_ENCODER=false`)
- No torch/sentence-transformers dependencies installed
- Falls back to Cohere API or LLM selector

**To enable self-hosted cross-encoder:**
- Set `ENABLE_CROSS_ENCODER=true`
- Install optional dependencies: `pip install -r requirements-cross-encoder.txt`

## Installation

### Production (Default - Fast Deploy)

Production should **NOT** install sentence-transformers:

```bash
pip install -r requirements.txt
```

This installs:
- FastAPI, uvicorn, psycopg, pgvector
- OpenAI, httpx, numpy
- **NO** torch, sentence-transformers, transformers

### Local Development (Optional)

If you want to test self-hosted cross-encoder locally:

```bash
pip install -r requirements-cross-encoder.txt
```

This installs everything from `requirements.txt` plus:
- `sentence-transformers>=2.2.0` (includes torch)

## Configuration

### Environment Variables

**`ENABLE_CROSS_ENCODER`** (default: `false`)
- `false` or unset: Cross-encoder model is NOT loaded
- `true`: Attempts to load self-hosted model (requires sentence-transformers)

**`COHERE_API_KEY`** (optional)
- If set, used as fallback when self-hosted cross-encoder is unavailable
- Cost: ~$1 per 1000 queries

## How It Works

### Lazy Loading

The cross-encoder model is **never loaded at import time**:

1. Module import: Only reads `ENABLE_CROSS_ENCODER` env var
2. First use: `_get_cross_encoder_model()` is called
3. Fast path: If `ENABLE_CROSS_ENCODER=false`, returns `(None, False)` immediately
4. Slow path: If enabled, imports `sentence_transformers` and loads model

### Fallback Chain

1. **Self-hosted cross-encoder** (if `ENABLE_CROSS_ENCODER=true` and installed)
2. **Cohere API** (if `COHERE_API_KEY` is set)
3. **LLM selector** (always available, used as final fallback)

## Production Deployment

### Render Settings

1. **Environment Variable**: `ENABLE_CROSS_ENCODER=false` (or leave unset)
2. **Build Command**: `pip install -r requirements.txt`
3. **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### Why Disabled by Default?

- **Fast startup**: No torch/sentence-transformers to download/load
- **Smaller image**: Saves ~500MB+ in dependencies
- **Faster deploys**: Build completes in seconds, not minutes
- **Cohere API works**: Production can use Cohere API for reranking

## Testing

### Import Smoke Test

Verify app imports without sentence-transformers:

```bash
pytest tests/test_import_smoke.py -v
```

This ensures:
- App imports successfully
- Cross-encoder returns `(None, False)` when disabled
- No import-time model loading

### Enable for Testing

To test self-hosted cross-encoder locally:

```bash
# Install dependencies
pip install -r requirements-cross-encoder.txt

# Set env var
export ENABLE_CROSS_ENCODER=true

# Run tests
pytest tests/ -v
```

## Troubleshooting

**"sentence-transformers not installed"**
- This is **expected** in production (disabled by default)
- System will use Cohere API or LLM selector instead

**"Cross-encoder failed to load model"**
- Check `ENABLE_CROSS_ENCODER=true` is set
- Verify `sentence-transformers` is installed
- Check model download (first run downloads ~100MB)

**Slow startup in production**
- Ensure `ENABLE_CROSS_ENCODER=false` (or unset)
- Verify `requirements.txt` doesn't include sentence-transformers
- Check Render logs for import-time errors

