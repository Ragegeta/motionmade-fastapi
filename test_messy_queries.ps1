$apiUrl = "https://api.motionmadebne.com.au"

$tests = @(
    "hw much 4 sparky",
    "r u licenced", 
    "saftey swich keeps goin off",
    "smok alarm wont stop beepin",
    "pwr out half house"
)

Write-Host "=== MESSY QUERY DIAGNOSIS ===" -ForegroundColor Cyan

foreach ($q in $tests) {
    $body = "{`"tenantId`":`"sparkys_electrical`",`"customerMessage`":`"$q`"}"
    $response = curl.exe -s -i -X POST "$apiUrl/api/v2/generate-quote-reply" -H "Content-Type: application/json" -d $body 2>&1
    
    # Parse headers
    $responseStr = $response | Out-String
    
    $hit = $responseStr -match "x-faq-hit:\s*true"
    
    if ($responseStr -match "x-normalized-input:\s*([^\r\n]+)") {
        $normalized = $Matches[1].Trim()
    } else {
        $normalized = "?"
    }
    
    if ($responseStr -match "x-fts-count:\s*(\d+)") {
        $fts = $Matches[1]
    } else {
        $fts = "?"
    }
    
    if ($responseStr -match "x-retrieval-stage:\s*([^\r\n]+)") {
        $stage = $Matches[1].Trim()
    } else {
        $stage = "?"
    }
    
    if ($responseStr -match "x-selector-called:\s*(\d+)") {
        $selector = $Matches[1]
    } else {
        $selector = "?"
    }
    
    $result = if ($hit) { "HIT" } else { "MISS" }
    $color = if ($hit) { "Green" } else { "Red" }
    
    Write-Host ""
    Write-Host "$result - `"$q`"" -ForegroundColor $color
    Write-Host "  Normalized: $normalized"
    Write-Host "  FTS count: $fts"
    Write-Host "  Stage: $stage"
    Write-Host "  Selector called: $selector"
}

