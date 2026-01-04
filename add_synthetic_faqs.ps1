[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [int]$Count = 100
)

$ErrorActionPreference = "Stop"

function Write-Utf8NoBom([string]$path, [string]$text) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($path, $text, $enc)
}

$tenantDir = Join-Path $PSScriptRoot ("tenants\{0}" -f $TenantId)
$faqsPath  = Join-Path $tenantDir "faqs.json"
if (-not (Test-Path $faqsPath)) { throw "Missing: $faqsPath" }

# Backup
$bak = Join-Path $tenantDir ("faqs.json.bak_{0}" -f (Get-Date -Format "yyyyMMdd_HHmmss"))
Copy-Item $faqsPath $bak -Force

$faqs = Get-Content $faqsPath -Raw | ConvertFrom-Json
if (-not $faqs) { $faqs = @() }

# Remove old synthetic format if it exists (keeps benchmark clean)
$faqs = @($faqs | Where-Object { $_.question -notmatch '^Benchmark FAQ\s+\d+\s+-\s+policy item\s+BENCH\d{3}' })

for ($i=1; $i -le $Count; $i++) {
  $token = ("BENCH{0:000}" -f $i)
  $price = 40 + $i

  # IMPORTANT: make it look like a real pricing question so fact gate triggers
  $q = "How much does benchmark item $token cost?"
  $a = "Benchmark item $token costs $$price. (Synthetic benchmark FAQ item.)"

  if (-not ($faqs | Where-Object { $_.question -eq $q })) {
    $faqs += [pscustomobject]@{ question=$q; answer=$a }
  }
}

$json = $faqs | ConvertTo-Json -Depth 10
Write-Utf8NoBom (Resolve-Path $faqsPath) $json

Write-Host "OK: added synthetic FAQs to $faqsPath (backup: $bak)"