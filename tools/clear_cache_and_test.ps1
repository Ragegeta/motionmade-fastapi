# Clear cache and test FTS OR fix
Write-Host "=== STEP 1: Clear Cache ===" -ForegroundColor Cyan

python -c "
from app.db import get_conn
with get_conn() as conn:
    conn.execute('DELETE FROM retrieval_cache WHERE tenant_id = %s', ('sparkys_electrical',))
    conn.commit()
    print('Cache cleared')
"

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to clear cache" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== STEP 2: Wait 5 seconds before testing ===" -ForegroundColor Cyan
Start-Sleep -Seconds 5

Write-Host ""
Write-Host "=== STEP 3: Run Production Tests ===" -ForegroundColor Cyan
& "$PSScriptRoot\test_fts_production.ps1"

