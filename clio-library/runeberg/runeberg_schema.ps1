# runeberg_schema.ps1
# Skapar ett schemalagt jobb i Windows Task Scheduler
# som kör runeberg_fas2_verk.py varje dag kl 02:00
#
# Kör som administratör:
#   .\runeberg_schema.ps1
#
# För att se jobbet:     Get-ScheduledTask -TaskName "RunebergFas2"
# För att ta bort det:   Unregister-ScheduledTask -TaskName "RunebergFas2" -Confirm:$false

# ── Justera dessa sökvägar ──────────────────────────────────────
$PythonPath  = "C:\Users\$env:USERNAME\AppData\Local\Programs\Python\Python312\python.exe"
$ScriptDir   = "C:\Users\$env:USERNAME\Documents\Runeberg"   # Mapp där skripten ligger
$ScriptName  = "runeberg_fas2_verk.py"
$LogFile     = "$ScriptDir\runeberg_log.txt"
# ────────────────────────────────────────────────────────────────

# Skapa mappen om den inte finns
if (-not (Test-Path $ScriptDir)) {
    New-Item -ItemType Directory -Path $ScriptDir | Out-Null
    Write-Host "Skapade mapp: $ScriptDir"
}

# Verifiera att Python finns
if (-not (Test-Path $PythonPath)) {
    # Försök hitta Python automatiskt
    $PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PythonPath) {
        Write-Host "VARNING: Python hittades inte på standardsökväg."
        Write-Host "Uppdatera `$PythonPath i skriptet manuellt."
    }
}

Write-Host "Python: $PythonPath"
Write-Host "Skript: $ScriptDir\$ScriptName"
Write-Host "Logg:   $LogFile"
Write-Host ""

# Bygg action: python runeberg_fas2_verk.py >> logg
$Action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "$ScriptName >> `"$LogFile`" 2>&1" `
    -WorkingDirectory $ScriptDir

# Trigger: varje dag kl 02:00
$Trigger = New-ScheduledTaskTrigger -Daily -At "02:00"

# Inställningar: kör om dator var i viloläge, kör inte på batteri
$Settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3)

# Registrera
Register-ScheduledTask `
    -TaskName    "RunebergFas2" `
    -Description "Hämtar verksidor från Runeberg.org (Arvas Familjebibliotek)" `
    -Action      $Action `
    -Trigger     $Trigger `
    -Settings    $Settings `
    -RunLevel    Limited `
    -Force

Write-Host ""
Write-Host "Schemalagt jobb 'RunebergFas2' skapat."
Write-Host "Kör varje dag kl 02:00. Logg skrivs till:"
Write-Host "  $LogFile"
Write-Host ""
Write-Host "Testa manuellt med:"
Write-Host "  Start-ScheduledTask -TaskName 'RunebergFas2'"
