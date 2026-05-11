$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = "HotWheelsBlinkitAgent"
$launcher = Join-Path $projectDir "run_hourly.bat"

if (-not (Test-Path $launcher)) {
    throw "Could not find $launcher"
}

$taskCommand = "cmd.exe /c cd /d `"$projectDir`" && `"$launcher`""
schtasks /Create /F /TN $taskName /SC HOURLY /MO 1 /ST 08:00 /TR $taskCommand /RL LIMITED | Out-Null

if ($LASTEXITCODE -ne 0) {
    $startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
    $startupLauncher = Join-Path $startupDir "HotWheelsBlinkitAgent.bat"
    $fallbackLauncher = Join-Path $projectDir "run_agent.bat"
    Set-Content -Path $startupLauncher -Encoding ASCII -Value @(
        "@echo off",
        "cd /d `"$projectDir`"",
        "`"$fallbackLauncher`""
    )
    Write-Host "Task Scheduler was not available. Installed Startup launcher instead:"
    Write-Host $startupLauncher
    Write-Host "It will start the long-running scheduler at Windows login."
    exit 0
}

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
Set-ScheduledTask -TaskName $taskName -Settings $settings | Out-Null

Write-Host "Installed scheduled task: $taskName"
Write-Host "It will run $launcher once every hour."
Write-Host "The Python config still controls active hours and custom notification rules."
