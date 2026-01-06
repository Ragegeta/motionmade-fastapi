[CmdletBinding()]
param(
  [string]$TenantId = "biz9_real",
  [string]$Mode = "strict",
  [string]$Origin = "https://motionmadebne.com.au"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== GENERATING TESTS ===" -ForegroundColor Cyan
.\generate_benchmark_tests.ps1 -TenantId $TenantId -Mode $Mode

Write-Host ""
Write-Host "=== RUNNING SUITE ===" -ForegroundColor Cyan  
.\run_suite_widget.ps1 -TenantId $TenantId -Mode $Mode -Origin $Origin



