# Register the mister MCP server as a scheduled task that starts at Windows boot, runs as the
# current user whether or not anyone is logged on (S4U: no stored password), and restarts on
# failure. Run from an elevated PowerShell:
#
#     powershell -ExecutionPolicy Bypass -File E:\MiSTer-CoreSkill\mcp\install_service.ps1
#
# As the user, not SYSTEM: the scripts read ~/.mister-core.env, and hwlock's JTAG markers live in
# the user's %LOCALAPPDATA%, which scripts run by hand must see too.
#
# After changing the server's code:
#     Stop-ScheduledTask mister-mcp; Start-ScheduledTask mister-mcp

$exe = Join-Path $PSScriptRoot ".venv\Scripts\mister-mcp.exe"
if (-not (Test-Path $exe)) { throw "no $exe; install the package first (README)" }

$action    = New-ScheduledTaskAction -Execute $exe -WorkingDirectory $PSScriptRoot
$trigger   = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
             -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
             -MultipleInstances IgnoreNew -StartWhenAvailable

Register-ScheduledTask -TaskName "mister-mcp" -Action $action -Trigger $trigger -Principal $principal `
    -Settings $settings -Description "MiSTer core MCP server, http://127.0.0.1:8770/mcp" -Force | Out-Null
# A server started by hand holds the port, and the task's copy would exit at once
Get-NetTCPConnection -LocalPort 8770 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
Start-ScheduledTask -TaskName "mister-mcp"
Start-Sleep 5
Get-ScheduledTask -TaskName "mister-mcp" | Select-Object TaskName, State
Get-NetTCPConnection -LocalPort 8770 -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, OwningProcess
