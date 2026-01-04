param(
    [Parameter(Mandatory=$true)]
    [string]$TenantId,

    [Parameter(Mandatory=$false)]
    [string]$BusinessName = ""
)

Write-Host "TenantId: $TenantId"
Write-Host "BusinessName: $BusinessName"

