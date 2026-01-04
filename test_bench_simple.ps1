[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$TenantId,
  [Parameter(Mandatory=$false)][string]$ApiUrl = "https://api.motionmadebne.com.au"
)
Write-Host "TenantId: $TenantId"
Write-Host "ApiUrl: $ApiUrl"
