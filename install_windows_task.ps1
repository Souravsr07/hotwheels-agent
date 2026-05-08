$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = "HotWheelsBlinkitAgent"
$launcher = Join-Path $projectDir "run_agent.bat"

if (-not (Test-Path $launcher)) {
    throw "Could not find $launcher"
}

$taskCommand = "cmd.exe /c cd /d `"$projectDir`" && `"$launcher`""
schtasks /Create /F /TN $taskName /SC ONLOGON /TR $taskCommand /RL LIMITED | Out-Null

if ($LASTEXITCODE -ne 0) {
    $startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
    $startupLauncher = Join-Path $startupDir "HotWheelsBlinkitAgent.bat"
    Set-Content -Path $startupLauncher -Encoding ASCII -Value @(
        "@echo off",
        "cd /d `"$projectDir`"",
        "`"$launcher`""
    )
    Write-Host "Task Scheduler was not available. Installed Startup launcher instead:"
    Write-Host $startupLauncher
    exit 0
}

Write-Host "Installed scheduled task: $taskName"
Write-Host "It will run $launcher at Windows login."
