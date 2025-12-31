[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$NewTenantId,
  [string]$TemplateTenantId = "motionmade",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

if ($NewTenantId -notmatch '^[a-zA-Z0-9_-]+$') { throw "Bad NewTenantId '$NewTenantId'. Use only letters/numbers/_/-" }
if ($TemplateTenantId -notmatch '^[a-zA-Z0-9_-]+$') { throw "Bad TemplateTenantId '$TemplateTenantId'." }

$root = $PSScriptRoot
if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }

function Write-Utf8NoBom([string]$Path, [string]$Content) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  [IO.File]::WriteAllText($Path, $Content, $enc)
}

$srcTenantDir = Join-Path $root (Join-Path "tenants" $TemplateTenantId)
$dstTenantDir = Join-Path $root (Join-Path "tenants" $NewTenantId)
$testsDir     = Join-Path $root "tests"
$dstTestFile  = Join-Path $testsDir ("$NewTenantId.json")

if (-not (Test-Path $srcTenantDir)) { throw "Template tenant dir not found: $srcTenantDir" }
if ((Test-Path $dstTenantDir) -and -not $Force) { throw "Tenant already exists: $dstTenantDir (use -Force to overwrite)" }

# Create dirs
if (Test-Path $dstTenantDir) { Remove-Item -Recurse -Force $dstTenantDir }
New-Item -ItemType Directory -Path $dstTenantDir | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dstTenantDir "backups") | Out-Null
if (-not (Test-Path $testsDir)) { New-Item -ItemType Directory -Path $testsDir | Out-Null }

# Copy + rewrite tenant files (faqs.json and variant_profile.json)
$srcFaqs    = Join-Path $srcTenantDir "faqs.json"
$srcProfile = Join-Path $srcTenantDir "variant_profile.json"
if (-not (Test-Path $srcFaqs)) { throw "Missing in template: $srcFaqs" }
if (-not (Test-Path $srcProfile)) { throw "Missing in template: $srcProfile" }

Copy-Item $srcFaqs (Join-Path $dstTenantDir "faqs.json") -Force
Copy-Item $srcProfile (Join-Path $dstTenantDir "variant_profile.json") -Force

# Make faqs_variants.json equal to faqs.json initially (pipeline will mutate it)
Copy-Item\ (Join-Path\ $dstTenantDir\ "faqs\.json")\ (Join-Path\ $dstTenantDir\ "faqs_variants\.json")\ -Force\n#\ Create\ an\ initial\ rollback\ target\ so\ pipeline\ can\ always\ rollback\ on\ first\ run\nCopy-Item\ (Join-Path\ $dstTenantDir\ "faqs_variants\.json")\ (Join-Path\ $dstTenantDir\ "last_good_faqs_variants\.json")\ -Force

# Create a starter tests file (intentionally minimal + forces you to fill must-hit tokens)
$starter = [ordered]@{
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
} | ConvertTo-Json -Depth 30

Write-Utf8NoBom -Path $dstTestFile -Content $starter

Write-Host "âœ… Tenant scaffolded:" -ForegroundColor Green
Write-Host "  $dstTenantDir"
Write-Host "âœ… Test scaffolded:" -ForegroundColor Green
Write-Host "  $dstTestFile"
Write-Host ""
Write-Host "NEXT: edit tenants\$NewTenantId\faqs.json, tenants\$NewTenantId\variant_profile.json, and tests\$NewTenantId.json (replace EDIT ME fields)."