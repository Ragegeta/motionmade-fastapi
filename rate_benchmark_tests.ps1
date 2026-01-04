[CmdletBinding()]
param(
  # If you pass nothing, it auto-picks the newest report in .\reports\
  [string]$ReportPath = ""
)

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
if (-not $root) { $root = Get-Location }

# Find newest report if none provided
if (-not $ReportPath) {
  $reportsDir = Join-Path $root "reports"
  if (-not (Test-Path $reportsDir)) { throw "Missing reports folder: $reportsDir" }

  $latest = Get-ChildItem $reportsDir -File -Filter "*.json" |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1

  if (-not $latest) { throw "No report JSON files found in: $reportsDir" }
  $ReportPath = $latest.FullName
}

if (-not (Test-Path $ReportPath)) { throw "Report not found: $ReportPath" }

$r = Get-Content $ReportPath -Raw | ConvertFrom-Json

Write-Host ""
Write-Host ("REPORT: {0}" -f $ReportPath)
Write-Host ("tenantId={0} mode={1} base={2} origin={3} endpoint={4}" -f $r.tenantId, $r.mode, $r.base, $r.origin, $r.endpoint)
Write-Host ("generated_at={0} hardFailCount={1}" -f $r.generated_at, $r.hardFailCount)
Write-Host ""

# Score summary if present
if ($r.score) {
  Write-Host "SCORE SUMMARY:"
  foreach ($p in $r.score.PSObject.Properties) {
    $k = $p.Name
    $v = $p.Value
    if ($null -ne $v.total -and $v.total -gt 0) {
      Write-Host ("  {0}: {1}/{2}" -f $k, $v.hit, $v.total)
    }
  }
  Write-Host ""
}

# Show failures (compact)
$fails = @()
if ($r.results) {
  foreach ($x in $r.results) {
    if ($x.fails -and $x.fails.Count -gt 0) { $fails += $x }
  }
}

Write-Host ("FAILURES: {0}" -f $fails.Count)
if ($fails.Count -gt 0) {
  Write-Host ""
  foreach ($x in ($fails | Select-Object -First 30)) {
    Write-Host ("- {0}" -f $x.name)
    Write-Host ("  Q: {0}" -f $x.question)
    Write-Host ("  branch={0} faq_hit={1} gate_hit={2} top_faq_id={3} score={4}" -f $x.x_debug_branch, $x.x_faq_hit, $x.x_fact_gate_hit, $x.x_top_faq_id, $x.x_retrieval_score)
    foreach ($f in $x.fails) { Write-Host ("  FAIL: {0}" -f $f) }
    Write-Host ""
  }
  if ($fails.Count -gt 30) { Write-Host "(showing first 30 failures only)" }
}