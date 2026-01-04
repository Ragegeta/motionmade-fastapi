[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$NewTenantId,
  [string]$TemplateTenantId = "motionmade",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

if ($NewTenantId -notmatch '^[a-zA-Z0-9_-]+$') { throw "Bad NewTenantId '$NewTenantId'. Use only letters/numbers/_/-" }
if ($TemplateTenantId -notmatch '^[a-zA-Z0-9_-]+$') { throw "Bad TemplateTenantId '$TemplateTenantId'." }

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $root) { $root = Get-Location }

function Ensure-Dir([string]$Path) {
  if (-not (Test-Path $Path)) { New-Item -ItemType Directory -Path $Path | Out-Null }
}

$srcTenantDir = Join-Path (Join-Path $root "tenants") $TemplateTenantId
$dstTenantDir = Join-Path (Join-Path $root "tenants") $NewTenantId
$testsDir     = Join-Path $root "tests"
$dstTestFile  = Join-Path $testsDir ("$NewTenantId.json")

if (-not (Test-Path $srcTenantDir)) { throw "Template tenant dir not found: $srcTenantDir" }
if ((Test-Path $dstTenantDir) -and -not $Force) { throw "Tenant already exists: $dstTenantDir (use -Force to overwrite)" }

# Create dirs
if (Test-Path $dstTenantDir) { Remove-Item -Recurse -Force $dstTenantDir }
Ensure-Dir $dstTenantDir
Ensure-Dir (Join-Path $dstTenantDir "backups")
Ensure-Dir $testsDir

# Copy tenant files
$srcFaqs    = Join-Path $srcTenantDir "faqs.json"
$srcProfile = Join-Path $srcTenantDir "variant_profile.json"
if (-not (Test-Path $srcFaqs)) { throw "Missing in template: $srcFaqs" }
if (-not (Test-Path $srcProfile)) { throw "Missing in template: $srcProfile" }

Copy-Item $srcFaqs    (Join-Path $dstTenantDir "faqs.json") -Force
Copy-Item $srcProfile (Join-Path $dstTenantDir "variant_profile.json") -Force

# Working artifact starts as faqs.json
Copy-Item (Join-Path $dstTenantDir "faqs.json") (Join-Path $dstTenantDir "faqs_variants.json") -Force
# Create initial rollback target so first pipeline run can always rollback
Copy-Item (Join-Path $dstTenantDir "faqs_variants.json") (Join-Path $dstTenantDir "last_good_faqs_variants.json") -Force

# Starter tests: 1 must-hit placeholder + 2 plumbing checks
$starterObj = [ordered]@{
  base     = "https://api.motionmadebne.com.au"
  endpoint = "/api/v2/generate-quote-reply"
  tests    = @(
    [ordered]@{
      name = "A) EDIT ME: Must-hit business fact (must hit)"
      question = "EDIT ME"
      expect_debug_branch_any = @("fact_hit")
      must_contain = @("EDIT_ME_TOKEN")
    },
    [ordered]@{
      name = "B) Unknown capability (must fallback; never general_ok)"
      question = "Do you do carpet steam cleaning?"
      expect_debug_branch_any = @("fact_miss","general_fallback")
    },
    [ordered]@{
      name = "C) General knowledge (must be general_ok)"
      question = "Why is the sky blue?"
      expect_debug_branch_any = @("general_ok")
    }
  )
}

$starterJson = $starterObj | ConvertTo-Json -Depth 30
Set-Content -Path $dstTestFile -Value $starterJson -Encoding UTF8

Write-Host "Tenant scaffolded: $dstTenantDir"
Write-Host "Test scaffolded:   $dstTestFile"
Write-Host "Next: edit tenants\$NewTenantId\faqs.json, tenants\$NewTenantId\variant_profile.json, and tests\$NewTenantId.json"
