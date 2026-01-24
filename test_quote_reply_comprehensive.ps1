param(
    [string]$TenantId = "motionmade_demo",
    [string]$Endpoint = "https://motionmade-fastapi.onrender.com/api/v2/generate-quote-reply",
    [int]$TimeoutSec = 30,
    [switch]$UseDebugHeaders
)

$ProgressPreference = "SilentlyContinue"

$token = ""
if ($UseDebugHeaders) {
    $token = (Get-Content .env | Where-Object { $_ -match "^ADMIN_TOKEN=" }) -replace "^ADMIN_TOKEN=", ""
}

$testSuite = @(
    # Pricing variations
    @{q="whats it cost"; expect="hit"; category="pricing"},
    @{q="how much"; expect="hit"; category="pricing"},
    @{q="how much does it cost"; expect="hit"; category="pricing"},
    @{q="pricing"; expect="hit"; category="pricing"},
    @{q="price"; expect="hit"; category="pricing"},
    @{q="what do you charge"; expect="hit"; category="pricing"},
    @{q="hw much"; expect="hit"; category="pricing"},
    
    # Service questions
    @{q="what do you do"; expect="hit"; category="service"},
    @{q="what services"; expect="hit"; category="service"},
    @{q="how does it work"; expect="hit"; category="service"},
    @{q="what is motionmade"; expect="hit"; category="service"},
    
    # Business questions
    @{q="what businesses is this for"; expect="hit"; category="business"},
    @{q="who is this for"; expect="hit"; category="business"},
    
    # Feature questions
    @{q="free trial"; expect="hit"; category="feature"},
    @{q="do you have a trial"; expect="hit"; category="feature"},
    @{q="can it handle typos"; expect="hit"; category="feature"},
    
    # General questions (should get AI answer, not error)
    @{q="what is the sun"; expect="general"; category="general"},
    @{q="tell me a joke"; expect="general"; category="general"},
    @{q="what is 2+2"; expect="general"; category="general"},
    
    # Edge cases
    @{q="hi"; expect="general"; category="greeting"},
    @{q="hello"; expect="general"; category="greeting"},
    @{q="thanks"; expect="general"; category="greeting"}
)

Write-Host "`n=== COMPREHENSIVE TEST SUITE ===" -ForegroundColor Cyan
$passed = 0
$failed = 0
$errors = @()

foreach ($t in $testSuite) {
    $body = @{tenantId=$TenantId; customerMessage=$t.q} | ConvertTo-Json
    try {
        $headers = @{}
        if ($UseDebugHeaders) {
            $headers["Authorization"] = "Bearer $token"
            $headers["X-Debug-Timings"] = "1"
        }

        $r = Invoke-WebRequest -Uri $Endpoint `
            -Method POST -Body $body -ContentType "application/json" `
            -Headers $headers -TimeoutSec $TimeoutSec -UseBasicParsing
        
        $content = $r.Content | ConvertFrom-Json
        $hit = $r.Headers["x-faq-hit"]
        $hasAnswer = $content.replyText -and $content.replyText -notmatch "went wrong"
        
        if ($t.expect -eq "hit") {
            $success = $hit -eq "true"
        } else {
            $success = $hasAnswer
        }
        
        if ($success) {
            $passed++
            Write-Host "[PASS] [$($t.category)] `"$($t.q)`""
        } else {
            $failed++
            $errors += @{query=$t.q; category=$t.category; expected=$t.expect; got=$content.replyText}
            $preview = $content.replyText
            if ($preview.Length -gt 50) { $preview = $preview.Substring(0, 50) + "..." }
            Write-Host "[FAIL] [$($t.category)] `"$($t.q)`" -> $preview"
        }
    } catch {
        $failed++
        $errors += @{query=$t.q; category=$t.category; expected=$t.expect; got="ERROR: $($_.Exception.Message)"}
        Write-Host "[FAIL] [$($t.category)] `"$($t.q)`" -> ERROR"
    }
}

Write-Host "`n=== RESULTS ===" -ForegroundColor Cyan
Write-Host "Passed: $passed / $($testSuite.Count)"
Write-Host "Failed: $failed"

if ($errors.Count -gt 0) {
    Write-Host "`n=== FAILURES ===" -ForegroundColor Red
    foreach ($e in $errors) {
        Write-Host "[$($e.category)] `"$($e.query)`" - expected: $($e.expected), got: $($e.got)"
    }
}
