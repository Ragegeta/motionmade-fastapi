# PowerShell Debug Endpoint Guide

## Why curl.exe Fails in PowerShell

### The Problem
1. **Argument Parsing**: PowerShell parses arguments before passing them to `curl.exe`, which can mangle JSON strings
2. **Quoting Issues**: PowerShell's quoting rules differ from bash - single quotes don't prevent variable expansion
3. **Encoding**: Special characters in JSON (quotes, backslashes) get interpreted by PowerShell's parser
4. **Bash Syntax**: `@-` (heredoc) is bash-specific and PowerShell doesn't understand it

### Example of What Breaks
```powershell
# This can fail because PowerShell interprets the JSON
curl.exe -d '{"customerMessage":"ur prices pls"}' ...

# PowerShell sees: {"customerMessage":"ur prices pls"}
# But may pass to curl.exe as: {customerMessage:ur prices pls} (quotes stripped)
```

### Why Invoke-RestMethod Fixes It
1. **Native JSON**: PowerShell's `ConvertTo-Json` creates properly encoded JSON strings
2. **No Shell Parsing**: JSON is passed directly to the HTTP client, bypassing shell argument parsing
3. **Proper Encoding**: Handles Unicode, special characters, and escaping automatically
4. **Type Safety**: PowerShell hashtables → JSON conversion is type-safe

## Single Query Test

```powershell
# Copy/paste this entire block
$token = (Get-Content "C:\MM\motionmade-fastapi\.env" | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
$renderUrl = "https://motionmade-fastapi.onrender.com"
$body = @{customerMessage="ur prices pls"} | ConvertTo-Json -Compress
$response = Invoke-RestMethod -Uri "$renderUrl/admin/api/tenant/sparkys_electrical/debug-query" -Method POST -Headers @{"Authorization"="Bearer $token"; "Content-Type"="application/json"} -Body $body -TimeoutSec 30
$response | ConvertTo-Json -Depth 10
Write-Host "`nKey fields:" -ForegroundColor Cyan
Write-Host "faq_hit: $($response.faq_hit)" -ForegroundColor $(if ($response.faq_hit) { "Green" } else { "Red" })
Write-Host "debug_branch: $($response.debug_branch)"
Write-Host "retrieval_score: $($response.retrieval_score)"
Write-Host "normalized_input: $($response.normalized_input)"
```

## Batch Test (4 Messages)

```powershell
# Copy/paste this entire block
$token = (Get-Content "C:\MM\motionmade-fastapi\.env" | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
$renderUrl = "https://motionmade-fastapi.onrender.com"
$tenantId = "sparkys_electrical"
$messages = @("how much do you charge", "ur prices pls", "are you licensed", "do you do plumbing")
foreach ($msg in $messages) {
    $body = @{customerMessage=$msg} | ConvertTo-Json -Compress
    $response = Invoke-RestMethod -Uri "$renderUrl/admin/api/tenant/$tenantId/debug-query" -Method POST -Headers @{"Authorization"="Bearer $token"; "Content-Type"="application/json"} -Body $body -TimeoutSec 30
    $hit = if ($response.faq_hit) { "HIT" } else { "MISS" }
    $branch = $response.debug_branch
    $score = if ($response.retrieval_score) { $response.retrieval_score } else { "n/a" }
    Write-Host "$hit | $branch | $score | '$msg'" -ForegroundColor $(if ($response.faq_hit) { "Green" } else { "Red" })
}
```

## Files Created

- `test_debug_endpoint.ps1` - Single query test with full output
- `test_debug_batch.ps1` - Batch test with one-line output per message

