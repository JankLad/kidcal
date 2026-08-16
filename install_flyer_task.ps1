# KidCal — install the standing local flyer pass as a Windows Scheduled Task.
#
# The cloud job (GitHub Actions) CANNOT do this: Facebook blocks datacenter IPs,
# so every `pass:local` source is skipped there. This task runs the Playwright
# harvest from this machine's residential IP on a schedule.
#
# Weekly on purpose: flyer-first orgs post a few times a month, and low-volume
# access keeps the Facebook pass unobtrusive. Runs Mondays 9:05am; if the
# machine is asleep at that time the task runs at the next wake.
#
# Usage:   powershell -ExecutionPolicy Bypass -File install_flyer_task.ps1
# Remove:  Unregister-ScheduledTask -TaskName "KidCal Flyer Pass" -Confirm:$false

$ErrorActionPreference = 'Stop'

$TaskName = "KidCal Flyer Pass"
$KidCal   = "C:\Users\User\KidCal"
$Python   = (Get-Command python).Source

if (-not (Test-Path "$KidCal\flyer_run.py")) {
    throw "flyer_run.py not found in $KidCal"
}

$action = New-ScheduledTaskAction -Execute $Python `
    -Argument "flyer_run.py" -WorkingDirectory $KidCal

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 9:05AM

# StartWhenAvailable catches up a run missed while the machine was off/asleep —
# this laptop is not always on (see the battery/stability notes).
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description `
    "KidCal: harvest Facebook flyer sources locally, parse to quarantined candidates, report new ones to data/flyer_review.md" `
    -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName' (Mondays 9:05am)."
Write-Host ""
Write-Host "One-time setup still required:"
Write-Host "  cd $KidCal"
Write-Host "  python browser_pass.py --login"
Write-Host ""
Write-Host "Run it now to test:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Read results in:     $KidCal\data\flyer_review.md"
