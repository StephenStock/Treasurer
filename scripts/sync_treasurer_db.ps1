param(
  [Parameter(Mandatory = $true)]
  [string]$PrimaryDb,

  [Parameter(Mandatory = $true)]
  [string]$BackupDb,

  [ValidateSet('SyncStart', 'Backup', 'Restore')]
  [string]$Mode = 'SyncStart'
)

$ErrorActionPreference = 'Stop'

$primaryResolved = [System.IO.Path]::GetFullPath($PrimaryDb)
$backupResolved = [System.IO.Path]::GetFullPath($BackupDb)
if ($primaryResolved -eq $backupResolved) {
  return
}

function Ensure-ParentDirectory {
  param([string]$Path)

  $directory = Split-Path -Parent $Path
  if ($directory -and -not (Test-Path -LiteralPath $directory)) {
    New-Item -ItemType Directory -Path $directory | Out-Null
  }
}

function Copy-Atomic {
  param(
    [string]$Source,
    [string]$Destination
  )

  Ensure-ParentDirectory -Path $Destination
  $temp = "$Destination.tmp"
  if (Test-Path -LiteralPath $temp) {
    Remove-Item -LiteralPath $temp -Force
  }

  Copy-Item -LiteralPath $Source -Destination $temp -Force
  Move-Item -LiteralPath $temp -Destination $Destination -Force
}

function Get-FileStamp {
  param([string]$Path)

  $item = Get-Item -LiteralPath $Path
  [pscustomobject]@{
    MTimeUtc = $item.LastWriteTimeUtc
    Size = [int64]$item.Length
  }
}

function Is-Newer {
  param(
    [pscustomobject]$Candidate,
    [pscustomobject]$Current
  )

  if ($Candidate.MTimeUtc -gt $Current.MTimeUtc) {
    return $true
  }

  if ($Candidate.MTimeUtc -lt $Current.MTimeUtc) {
    return $false
  }

  return $Candidate.Size -gt $Current.Size
}

switch ($Mode) {
  'Backup' {
    if (Test-Path -LiteralPath $PrimaryDb) {
      Copy-Atomic -Source $PrimaryDb -Destination $BackupDb
    }
  }
  'Restore' {
    if (Test-Path -LiteralPath $BackupDb) {
      Copy-Atomic -Source $BackupDb -Destination $PrimaryDb
    }
  }
  default {
    $primaryExists = Test-Path -LiteralPath $PrimaryDb
    $backupExists = Test-Path -LiteralPath $BackupDb

    if (-not $primaryExists -and $backupExists) {
      Copy-Atomic -Source $BackupDb -Destination $PrimaryDb
      return
    }

    if ($primaryExists -and -not $backupExists) {
      Copy-Atomic -Source $PrimaryDb -Destination $BackupDb
      return
    }

    if ($primaryExists -and $backupExists) {
      $primaryStamp = Get-FileStamp -Path $PrimaryDb
      $backupStamp = Get-FileStamp -Path $BackupDb

      if (Is-Newer -Candidate $backupStamp -Current $primaryStamp) {
        Copy-Atomic -Source $BackupDb -Destination $PrimaryDb
      }
      elseif (Is-Newer -Candidate $primaryStamp -Current $backupStamp) {
        Copy-Atomic -Source $PrimaryDb -Destination $BackupDb
      }
    }
  }
}
