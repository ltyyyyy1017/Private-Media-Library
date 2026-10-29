param([Parameter(Mandatory=$true)][string]$ShareFolder)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$OutputEncoding = [Console]::OutputEncoding
. "$PSScriptRoot\Gate.ps1"
if (([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run the file server as a normal user, not administrator.' }
$folder = (Resolve-Path -LiteralPath $ShareFolder).Path
if (-not (Test-Path -LiteralPath $folder -PathType Container)) { throw 'ShareFolder must be a directory.' }
if ($folder -eq [IO.Path]::GetPathRoot($folder) -or $folder -eq $env:USERPROFILE -or $PSScriptRoot.StartsWith($folder.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase) -or $folder -eq $PSScriptRoot) { throw 'Choose a dedicated data folder, not a drive, profile or program folder.' }
$hotspot = Get-Hotspot
Assert-Rules $hotspot
$python = "$PSScriptRoot\.venv\Scripts\python.exe"
$serverArgs = @("`"$PSScriptRoot\app.py`"")
if (Test-Path -LiteralPath "$PSScriptRoot\Yingyu.exe") {
    $python = "$PSScriptRoot\Yingyu.exe"
    $serverArgs = @('--serve')
}
if (-not (Test-Path -LiteralPath $python)) { throw 'Install dependencies using the README first.' }
# Lock certificate storage to the current account and SYSTEM.
$state = New-Item -ItemType Directory -Path "$PSScriptRoot\private-state" -Force
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
& icacls.exe $state.FullName /inheritance:r /grant:r "*$($sid):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot protect TLS key directory.' }
$job = Start-Process -FilePath $python -ArgumentList ($serverArgs + @('--root',"`"$folder`"",'--ip','192.168.137.1','--network','192.168.137.0/24')) -NoNewWindow -PassThru
try {
    while (-not $job.HasExited) {
        Start-Sleep -Seconds 2
        $current = Get-Hotspot
        if ($current.InterfaceGuid -ne $hotspot.InterfaceGuid) { throw 'Hotspot adapter changed.' }
        Assert-Rules $current
        $job.Refresh()
    }
} finally {
    if (-not $job.HasExited) { Stop-Process -Id $job.Id }
}
