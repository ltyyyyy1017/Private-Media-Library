param([Parameter(Mandatory=$true)][string]$ProgramFolder)
$ErrorActionPreference = 'Stop'
# Dispatch through the existing desktop Explorer, which owns the normal-user
# token. Do not remove the server's administrator guard.
$shell = New-Object -ComObject Shell.Application
$desktop = $shell.Windows().FindWindowSW(0, 0, 8, 0, 1)
if ($null -eq $desktop) { throw 'Cannot find normal-user Windows desktop Explorer.' }
$python = Join-Path $ProgramFolder '.venv\Scripts\pythonw.exe'
$script = Join-Path $ProgramFolder 'manager.py'
if (Test-Path -LiteralPath (Join-Path $ProgramFolder 'Yingyu.exe')) {
    $desktop.Document.Application.ShellExecute((Join-Path $ProgramFolder 'Yingyu.exe'), '--normal-user', $ProgramFolder, 'open', 1)
    exit 0
}
$desktop.Document.Application.ShellExecute($python, ('"' + $script + '" --normal-user'), $ProgramFolder, 'open', 1)
