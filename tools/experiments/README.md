# Experiments and Ad-hoc Scripts

This directory contains experimental scripts and ad-hoc benchmark scripts that are **not part of the CI test suite**.

## Contents

- `test_cross_encoder.py` - Ad-hoc benchmark script for cross-encoder testing
- `test_llm_fallback.py` - Experimental LLM fallback testing script
- `test_normalized_scores.py` - Benchmark script for normalized scoring

## Note

These scripts are **not unit tests** and should **not** be run as part of the pytest test suite. They are kept here for reference and manual execution when needed.

## Running Real Tests

To run the actual test suite:

```bash
python -m pytest -q tests
```







