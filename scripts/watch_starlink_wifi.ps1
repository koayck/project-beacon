#requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Path
$ToggleScript = Join-Path $ScriptDir 'toggle_starlink_tc.ps1'

$TargetSsid           = if ($env:TARGET_SSID)                    { $env:TARGET_SSID }                    else { 'Starlink' }
$CheckInterval        = if ($env:CHECK_INTERVAL_SECONDS)         { [int]$env:CHECK_INTERVAL_SECONDS }    else { 3 }
$ForceAfterDisconnect = if ($null -ne $env:FORCE_STARLINK_AFTER_DISCONNECT) {
                            $env:FORCE_STARLINK_AFTER_DISCONNECT -notin @('0', 'false', 'no', 'off')
                        } else { $true }
$ForceRetryEvery      = if ($env:FORCE_RETRY_EVERY_CYCLES)       { [int]$env:FORCE_RETRY_EVERY_CYCLES }  else { 3 }

if (-not (Test-Path $ToggleScript)) {
    Write-Error "Toggle script not found: $ToggleScript"
    exit 1
}

function Get-ActiveSsids {
    $out = netsh wlan show interfaces 2>$null
    if (-not $out) { return @() }
    $ssids = @()
    foreach ($line in $out) {
        if ($line -match '^\s*SSID\s*:\s*(.+)$') {
            $s = $Matches[1].Trim()
            if ($s) { $ssids += $s }
        }
    }
    $ssids
}

function Invoke-WifiConnect([string]$Ssid) {
    Write-Host "[starlink-wifi-watch] attempting to connect to: $Ssid"
    # Requires a saved profile named $Ssid (created once via Windows UI or `netsh wlan add profile`)
    netsh wlan connect name="$Ssid" ssid="$Ssid" 2>&1 | Write-Host
    return $LASTEXITCODE -eq 0
}

function Invoke-Toggle([string]$Mode) {
    $env:STARLINK_MOCK_SOURCE = 'wifi-watch'
    $env:TARGET_SSID          = $TargetSsid
    & $ToggleScript -Mode $Mode
}

Write-Host "[starlink-wifi-watch] target=$TargetSsid interval=${CheckInterval}s force=$ForceAfterDisconnect"

$lastMode        = ''
$lastSsids       = ''
$cyclesSinceDown = 0

while ($true) {
    try {
        $active     = @(Get-ActiveSsids)
        $ssidJoined = ($active -join ',')
        $onTarget   = $active -contains $TargetSsid

        if ($onTarget) {
            $cyclesSinceDown = 0
            if ($lastMode -ne 'starlink' -or $ssidJoined -ne $lastSsids) {
                Write-Host "[starlink-wifi-watch] SSID=$ssidJoined -> starlink"
                Invoke-Toggle 'starlink'
                $lastMode = 'starlink'
            }
        }
        else {
            if ($lastMode -ne 'degraded' -or $ssidJoined -ne $lastSsids) {
                Write-Host "[starlink-wifi-watch] SSID=$ssidJoined -> degraded"
                Invoke-Toggle 'degraded'
                $lastMode = 'degraded'
            }
            if ($ForceAfterDisconnect) {
                $cyclesSinceDown++
                if ($cyclesSinceDown -ge $ForceRetryEvery) {
                    $cyclesSinceDown = 0
                    [void](Invoke-WifiConnect $TargetSsid)
                }
            }
        }

        $lastSsids = $ssidJoined
    }
    catch {
        Write-Warning "[starlink-wifi-watch] iteration failed: $_"
    }

    Start-Sleep -Seconds $CheckInterval
}
