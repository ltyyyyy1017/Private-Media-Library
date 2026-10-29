# Run once in an elevated PowerShell after enabling Mobile Hotspot.
$ErrorActionPreference = 'Stop'
$stage = 'Load configuration'
try {
. "$PSScriptRoot\Gate.ps1"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this setup script as administrator.' }
$stage = 'Discover hotspot ICS interface'
$hotspot = Get-Hotspot -Discover
$other = Get-OtherAliases $hotspot
if (-not $other.Count) { throw 'No other interface found; refusing ambiguous configuration.' }
$stage = 'Create firewall rules'
foreach ($name in @('HotspotFiles-Allow','HotspotFiles-BlockOther','HotspotFiles-BlockOutside')) {
    Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
}
New-NetFirewallRule -Name 'HotspotFiles-BlockOther' -DisplayName 'HotspotFiles block other interfaces' -Direction Inbound -Action Block -Protocol TCP -LocalPort 8443 -InterfaceAlias $other -Profile Any | Out-Null
New-NetFirewallRule -Name 'HotspotFiles-BlockOutside' -DisplayName 'HotspotFiles block outside subnet' -Direction Inbound -Action Block -Protocol TCP -LocalPort 8443 -InterfaceAlias $hotspot.Name -RemoteAddress @('0.0.0.1-192.168.136.255','192.168.138.0-255.255.255.254') -Profile Any | Out-Null
New-NetFirewallRule -Name 'HotspotFiles-Allow' -DisplayName 'HotspotFiles allow hotspot only' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8443 -InterfaceAlias $hotspot.Name -LocalAddress 192.168.137.1 -RemoteAddress 192.168.137.0/24 -Profile Any | Out-Null
$stage = 'Verify effective firewall rules'
Assert-Rules $hotspot
@{ Guid = $hotspot.InterfaceGuid.ToString() } | ConvertTo-Json | Set-Content -LiteralPath "$PSScriptRoot\hotspot.json" -Encoding UTF8
Write-Host 'Firewall prepared. Close this elevated terminal; use Start.ps1 as your normal account.'
@{ok=$true; stage='Complete'; message='Firewall configuration verified.'} | ConvertTo-Json | Set-Content -LiteralPath "$PSScriptRoot\setup-result.json" -Encoding UTF8
exit 0
} catch {
    @{ok=$false; stage=$stage; message=$_.Exception.Message; detail=($_ | Out-String); location=$_.ScriptStackTrace} | ConvertTo-Json | Set-Content -LiteralPath "$PSScriptRoot\setup-result.json" -Encoding UTF8
    exit 1
}
