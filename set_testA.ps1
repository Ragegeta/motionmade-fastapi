[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [Parameter(Mandatory=$true)][string]$Question,
  [Parameter(Mandatory=$true)][string]$Token
)

$path = ".\tests\$TenantId.json"
if (-not (Test-Path $path)) { throw "Missing: $path" }

$j = Get-Content $path -Raw | ConvertFrom-Json
$j.tests[0].name = "A) Must-hit business fact (must hit)"
$j.tests[0].question = $Question
$j.tests[0].expect_debug_branch_any = @("fact_hit")
$j.tests[0].must_contain = @($Token)

($j | ConvertTo-Json -Depth 50) | Set-Content -Encoding UTF8 $path
"patched test A in $path"
