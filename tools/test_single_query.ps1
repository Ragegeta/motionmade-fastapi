# Test a single query and show raw response
$apiUrl = "https://api.motionmadebne.com.au"
$query = "smoke alarm beeping"

$body = @{tenantId="sparkys_electrical"; customerMessage=$query} | ConvertTo-Json -Compress

Write-Host "=== Testing: $query ===" -ForegroundColor Cyan
Write-Host "Request body: $body" -ForegroundColor Gray
Write-Host ""

$r = curl.exe -s -i -X POST "$apiUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" -d $body 2>&1

Write-Host "=== RAW RESPONSE HEADERS ===" -ForegroundColor Yellow
$headerLines = $r -split "`n" | Where-Object { $_ -match "^(HTTP|x-|content-)" -or $_ -match "^\r?$" }
$headerLines | Select-Object -First 30

Write-Host ""
Write-Host "=== PARSED VALUES ===" -ForegroundColor Yellow

# Try different patterns
if ($r -match "x-fts-count:\s*(\d+)") {
    Write-Host "FTS Count (pattern 1): $($Matches[1])" -ForegroundColor Green
} else {
    Write-Host "FTS Count (pattern 1): NOT FOUND" -ForegroundColor Red
}

if ($r -match "(?i)x-fts-count[:\s]+(\d+)") {
    Write-Host "FTS Count (pattern 2): $($Matches[1])" -ForegroundColor Green
} else {
    Write-Host "FTS Count (pattern 2): NOT FOUND" -ForegroundColor Red
}

# Check for x-faq-hit
if ($r -match "x-faq-hit:\s*true") {
    Write-Host "FAQ Hit: TRUE" -ForegroundColor Green
} elseif ($r -match "x-faq-hit:\s*false") {
    Write-Host "FAQ Hit: FALSE" -ForegroundColor Yellow
} else {
    Write-Host "FAQ Hit: NOT FOUND" -ForegroundColor Red
}

# Show all x- headers
Write-Host ""
Write-Host "=== ALL X- HEADERS ===" -ForegroundColor Yellow
$r -split "`n" | Where-Object { $_ -match "^x-" } | ForEach-Object { Write-Host $_ }

