# Run hybrid retrieval tests
# Usage: .\run_retrieval_tests.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  HYBRID RETRIEVAL TEST SUITE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Activate venv
if (Test-Path ".\.venv\Scripts\Activate.ps1") {
    .\.venv\Scripts\Activate
} else {
    Write-Host "Warning: .venv not found, using system Python" -ForegroundColor Yellow
}

# Run unit tests (fast, no network)
Write-Host "`n=== UNIT TESTS ===" -ForegroundColor Yellow
python -m pytest tests/test_hybrid_retrieval.py -v -k "not integration" --tb=short

# Run integration tests (requires API)
Write-Host "`n=== INTEGRATION TESTS ===" -ForegroundColor Yellow
python -m pytest tests/test_hybrid_retrieval.py -v -k "integration" --tb=short -x

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  TESTS COMPLETE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

