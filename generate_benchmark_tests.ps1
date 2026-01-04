[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [ValidateSet("strict","stress")][string]$Mode = "strict",
  [string]$OutPath = "",
  [int]$MaxFaqs = 0
)

$ErrorActionPreference = "Stop"

function Write-Utf8NoBom([string]$Path, [string]$Text) {
  $enc = New-Object System.Text.UTF8Encoding($false)
  $dir = Split-Path -Parent $Path
  if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force $dir | Out-Null }
  [System.IO.File]::WriteAllText($Path, $Text, $enc)
}

function Normalize([string]$s) {
  if ($null -eq $s) { return "" }
  $t = $s.ToLowerInvariant().Trim()
  $t = [regex]::Replace($t, "\s+", " ")
  return $t
}

function Pick-MustTokens([string]$Question, [string]$Answer) {
  $must = @()

  if ($Question -match "BENCH\d{3}") { $must += $Matches[0] }

  if ($Answer) {
    $m = [regex]::Match($Answer, "\$\s*\d+")
    if ($m.Success) { $must += ([regex]::Replace($m.Value, "\s", "")) }

    if ($must.Count -gt 0) { return @($must | Select-Object -Unique) }

    $m2 = [regex]::Match($Answer, "(billed at cost|invoice|deposit|parking|oven|fridge|pets|refund|reschedule|bond|standard|deep)", "IgnoreCase")
    if ($m2.Success) { return @($m2.Value) }

    $s = ([regex]::Replace($Answer, "\s+", " ")).Trim()
    if ($s.Length -ge 12) { return @($s.Substring(0,12)) }
  }

  return @()
}

$root = $PSScriptRoot
if (-not $root) { $root = Split-Path -Parent $MyInvocation.MyCommand.Path }

$variantsPath = Join-Path $root ("tenants\{0}\faqs_variants.json" -f $TenantId)
if (-not (Test-Path $variantsPath)) { throw "Missing: $variantsPath (run run_faq_pipeline.ps1 first)" }

if (-not $OutPath) { $OutPath = Join-Path $root ("tests\{0}.json" -f $TenantId) }

$items = Get-Content $variantsPath -Raw | ConvertFrom-Json
if (-not $items) { throw "Loaded empty faqs_variants.json: $variantsPath" }

if ($MaxFaqs -gt 0) { $items = @($items | Select-Object -First $MaxFaqs) }

$tests = @()

# Smoke tests
$tests += @{
  name="SMOKE) General knowledge stays general_ok"
  question="Why is the sky blue?"
  expect_debug_branch_any=@("general_ok")
  severity="hard"
  category="strict_required"
}
$tests += @{
  name="SMOKE) Unknown capability must not become general_ok"
  question="Do you do carpet steam cleaning?"
  expect_debug_branch_any=@("fact_miss","general_fallback")
  severity="hard"
  category="strict_required"
}

$idx = 0
foreach ($f in $items) {
  $idx++
  $q = [string]$f.question
  $a = [string]$f.answer
  $must = Pick-MustTokens $q $a

  $vars = @()
  if ($f.variants) { $vars = @($f.variants | ForEach-Object { [string]$_ }) }
  $vars = @($vars | Where-Object { $_ -and $_.Trim().Length -gt 0 } | Select-Object -Unique)

  # STRICT: exact + up to 2 variants (all hard)
  $tests += @{
    name=("FAQ {0}/{1}) {2} [exact]" -f $idx, $items.Count, $q)
    question=$q
    expect_debug_branch_any=@("fact_hit","fact_rewrite_hit")
    must_contain=$must
    severity="hard"
    category="strict_required"
  }

  $take = 2
  $vCount = 0
  foreach ($v in $vars) {
    if ($vCount -ge $take) { break }
    $vCount++
    $tests += @{
      name=("FAQ {0}/{1}) {2} [variant {3}]" -f $idx, $items.Count, $q, $vCount)
      question=$v
      expect_debug_branch_any=@("fact_hit","fact_rewrite_hit")
      must_contain=$must
      severity="hard"
      category="strict_required"
    }
  }

  if ($Mode -eq "stress") {
    $tests += @{
      name=("FAQ {0}/{1}) stress prefix" -f $idx, $items.Count)
      question=("Quick question: " + $q + " Please advise.")
      expect_debug_branch_any=@("fact_hit","fact_rewrite_hit","fact_miss","general_fallback")
      must_contain=$must
      severity="soft"
      category="stress_business"
    }
    $tests += @{
      name=("FAQ {0}/{1}) stress lowercase" -f $idx, $items.Count)
      question=(Normalize $q)
      expect_debug_branch_any=@("fact_hit","fact_rewrite_hit","fact_miss","general_fallback")
      must_contain=$must
      severity="soft"
      category="stress_business"
    }
    $tests += @{
      name=("FAQ {0}/{1}) stress typo" -f $idx, $items.Count)
      question=([regex]::Replace($q, "ing", "in g"))
      expect_debug_branch_any=@("fact_hit","fact_rewrite_hit","fact_miss","general_fallback")
      must_contain=$must
      severity="soft"
      category="stress_business"
    }
    $tests += @{
      name=("FAQ {0}/{1}) stress multi-intent" -f $idx, $items.Count)
      question=($q + " Also: " + [string]$items[0].question)
      expect_debug_branch_any=@("fact_hit","fact_rewrite_hit","fact_miss","general_fallback")
      must_contain=$must
      severity="soft"
      category="stress_business"
    }
  }
}

Write-Utf8NoBom $OutPath ($tests | ConvertTo-Json -Depth 10)
Write-Host ("OK: wrote {0} tests -> {1} (mode={2})" -f $tests.Count, $OutPath, $Mode)