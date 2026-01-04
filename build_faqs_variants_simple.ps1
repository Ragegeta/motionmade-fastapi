[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId
)

$ErrorActionPreference = "Stop"

function Write-Utf8NoBom([string]$path, [string]$text) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($path, $text, $enc)
}

$tenantDir = Join-Path $PSScriptRoot ("tenants\{0}" -f $TenantId)
$faqsPath  = Join-Path $tenantDir "faqs.json"
$outPath   = Join-Path $tenantDir "faqs_variants.json"

if (-not (Test-Path $faqsPath)) { throw "Missing: $faqsPath" }

$faqs = Get-Content $faqsPath -Raw | ConvertFrom-Json
if (-not $faqs) { throw "faqs.json loaded empty: $faqsPath" }

# Ensure every item has a variants array (basic, but enough for benchmarking)
$out = @()
foreach ($f in $faqs) {
  $q = [string]$f.question
  $a = [string]$f.answer

  $vars = @()
  if ($q) {
    $vars += $q
    $vars += ($q.ToLowerInvariant())
    $vars += ("Price for: " + $q)
    $vars += ("Cost: " + $q)
  }

  $out += [pscustomobject]@{
    question = $q
    answer   = $a
    variants = @($vars | Select-Object -Unique)
  }
}

Write-Utf8NoBom $outPath ($out | ConvertTo-Json -Depth 10)
Write-Host ("OK: built {0} items -> {1}" -f $out.Count, $outPath)