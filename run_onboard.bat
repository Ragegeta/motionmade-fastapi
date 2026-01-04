@echo off
cd /d C:\MM\motionmade-fastapi
powershell.exe -NoProfile -ExecutionPolicy Bypass -File new_tenant_onboard.ps1 -TenantId biz9_real -AdminBase https://motionmade-fastapi.onrender.com -PublicBase https://api.motionmadebne.com.au -Origin https://motionmadebne.com.au


