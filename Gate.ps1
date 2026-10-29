$ErrorActionPreference = 'Stop'
function Get-Hotspot([switch]$Discover) {
    # Modern Windows Mobile Hotspot is not reliably reported as a private
    # connection by the legacy HNetShare COM API. Check its actual WinRT state.
    $null = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]
    $null = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]
    $active = @([Windows.Networking.Connectivity.NetworkInformation]::GetConnectionProfiles() | ForEach-Object {
        try {
            $tether = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($_)
            if ($tether.TetheringOperationalState.ToString() -eq 'On') { $true }
        } catch { }
    })
    if (-not $active.Count) { throw 'Windows Mobile Hotspot is OFF or its state cannot be verified. Enable Mobile Hotspot in Settings first.' }
    if ($Discover) {
        $addresses = @(Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -eq '192.168.137.1' -and $_.PrefixLength -eq 24 })
        if ($addresses.Count -ne 1) { throw 'Cannot uniquely identify hotspot address 192.168.137.1/24.' }
        $adapter = Get-NetAdapter -IncludeHidden -InterfaceIndex $addresses[0].InterfaceIndex
        if ($adapter.InterfaceDescription -notlike '*Wi-Fi Direct*' -or $adapter.Status -ne 'Up') { throw 'Hotspot address does not belong to an active Wi-Fi Direct adapter.' }
    } else {
        $saved = Get-Content -LiteralPath "$PSScriptRoot\hotspot.json" -Raw | ConvertFrom-Json
        $adapter = Get-NetAdapter -IncludeHidden | Where-Object { $_.InterfaceGuid.ToString() -eq $saved.Guid }
        if (@($adapter).Count -ne 1) { throw 'Configured hotspot adapter is missing; run setup again.' }
    }
    $ip = @(Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 | Where-Object { $_.IPAddress -eq '192.168.137.1' -and $_.PrefixLength -eq 24 })
    if ($ip.Count -ne 1) { throw 'This version requires hotspot address 192.168.137.1/24. Refusing to use another interface.' }
    $usedProfiles = @(Get-NetConnectionProfile | ForEach-Object { if ($_.NetworkCategory -eq 'DomainAuthenticated') { 'Domain' } else { $_.NetworkCategory.ToString() } } | Select-Object -Unique)
    if (-not $usedProfiles.Count) { throw 'Cannot identify active firewall profiles.' }
    if (@(Get-NetFirewallProfile -PolicyStore ActiveStore | Where-Object { $_.Name -in $usedProfiles -and (-not $_.Enabled -or $_.DefaultInboundAction -eq 'Allow') }).Count) { throw 'An ACTIVE Windows firewall profile is disabled or allows inbound traffic by default.' }
    return $adapter
}
function Get-OtherAliases($hotspot) {
    return @(Get-NetIPInterface | Where-Object { $_.InterfaceIndex -ne $hotspot.ifIndex -and $_.InterfaceAlias -notlike 'Loopback*' } | Select-Object -ExpandProperty InterfaceAlias -Unique | Sort-Object)
}
function Assert-Rules($hotspot) {
    foreach ($name in @('HotspotFiles-Allow','HotspotFiles-BlockOther','HotspotFiles-BlockOutside')) {
        $rule = Get-NetFirewallRule -PolicyStore ActiveStore -Name $name
        if ($rule.Enabled -ne 'True' -or $rule.Direction -ne 'Inbound' -or $rule.Profile -ne 'Any') { throw "Invalid firewall rule: $name" }
        $port = $rule | Get-NetFirewallPortFilter
        if ($port.LocalPort -ne '8443' -or $port.Protocol -ne 'TCP') { throw 'Firewall port changed.' }
        $iface = @($rule | Get-NetFirewallInterfaceFilter | Select-Object -ExpandProperty InterfaceAlias)
        $addr = $rule | Get-NetFirewallAddressFilter
        if ($name -eq 'HotspotFiles-BlockOther') {
            $expected = Get-OtherAliases $hotspot
            if ($rule.Action -ne 'Block' -or @(Compare-Object ($iface | Sort-Object) $expected).Count -ne 0 -or $addr.RemoteAddress -ne 'Any' -or $addr.LocalAddress -ne 'Any') { throw 'Other-interface firewall isolation changed.' }
        } elseif ($name -eq 'HotspotFiles-Allow') {
            if ($rule.Action -ne 'Allow' -or $iface.Count -ne 1 -or $iface[0] -ne $hotspot.Name -or $addr.LocalAddress -ne '192.168.137.1' -or $addr.RemoteAddress -notin @('192.168.137.0/255.255.255.0','192.168.137.0/24')) { throw 'Hotspot allow rule changed.' }
        } else {
            if ($rule.Action -ne 'Block' -or $iface.Count -ne 1 -or $iface[0] -ne $hotspot.Name -or $addr.LocalAddress -ne 'Any' -or @(Compare-Object ($addr.RemoteAddress | Sort-Object) (@('0.0.0.1-192.168.136.255','192.168.138.0-255.255.255.254') | Sort-Object)).Count) { throw 'Outside-subnet firewall rule changed.' }
        }
    }
}
