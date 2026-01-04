# Test wrapper
param(
    [string]$TenantId = "biz9_real",
    [string]$AdminBase = "https://motionmade-fastapi.onrender.com",
    [string]$PublicBase = "https://api.motionmadebne.com.au",
    [string]$Origin = "https://motionmadebne.com.au"
)

& ".\new_tenant_onboard.ps1" -TenantId $TenantId -AdminBase $AdminBase -PublicBase $PublicBase -Origin $Origin


