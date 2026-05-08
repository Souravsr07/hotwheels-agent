$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = "HotWheelsBlinkitAgent"
$launcher = Join-Path $projectDir "run_agent.bat"

if (-not (Test-Path $launcher)) {
    throw "Could not find $launcher"
}

$action = New-ScheduledTaskAction -Execute $launcher -WorkingDirectory $projectDir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Runs the Hot Wheels Blinkit collector agent at Windows login." `
    -Force | Out-Null

Write-Host "Installed scheduled task: $taskName"
Write-Host "It will run $launcher at Windows login."
