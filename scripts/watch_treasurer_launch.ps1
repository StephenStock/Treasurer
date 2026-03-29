param(
  [Parameter(Mandatory = $true)]
  [int]$FlaskPid,

  [Parameter(Mandatory = $true)]
  [string]$ExitSignalPath,

  [Parameter(Mandatory = $true)]
  [string]$PrimaryDb,

  [Parameter(Mandatory = $true)]
  [string]$BackupDb
)

$ErrorActionPreference = 'Stop'

while ($true) {
  if (Test-Path -LiteralPath $ExitSignalPath) {
    break
  }

  if (-not (Get-Process -Id $FlaskPid -ErrorAction SilentlyContinue)) {
    break
  }

  Start-Sleep -Milliseconds 200
}

if (Get-Process -Id $FlaskPid -ErrorAction SilentlyContinue) {
  Stop-Process -Id $FlaskPid -Force -ErrorAction SilentlyContinue
}

Remove-Item -LiteralPath $ExitSignalPath -Force -ErrorAction SilentlyContinue

& "$PSScriptRoot\sync_treasurer_db.ps1" -PrimaryDb $PrimaryDb -BackupDb $BackupDb -Mode Backup
