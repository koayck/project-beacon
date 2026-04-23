#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateSet('starlink', 'degraded', 'direct', 'clear', 'status')]
    [string]$Mode = 'starlink'
)

$ErrorActionPreference = 'Stop'

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptDir
$StatusFile = Join-Path $RepoRoot '.starlink-mock-status'
$TargetSsid = if ($env:TARGET_SSID)          { $env:TARGET_SSID }          else { 'Starlink' }
$Source     = if ($env:STARLINK_MOCK_SOURCE) { $env:STARLINK_MOCK_SOURCE } else { 'manual' }

$StarlinkQdisc = 'delay 35ms 8ms distribution normal loss 0.8% rate 150mbit'
$DegradedQdisc = 'delay 75ms 40ms distribution normal loss 3% rate 50mbit'

function Get-BeaconContainers {
    $ids = [System.Collections.Generic.List[string]]::new()

    Push-Location $RepoRoot
    try {
        $composeIds = docker compose ps -q beacon-01 beacon-02 beacon-03 beacon-04 beacon-05 2>$null
        foreach ($id in @($composeIds)) {
            $trimmed = "$id".Trim()
            if ($trimmed) { [void]$ids.Add($trimmed) }
        }
    } finally {
        Pop-Location
    }

    $psLines = docker ps --format '{{.ID}} {{.Names}}' 2>$null
    foreach ($line in @($psLines)) {
        if ($line -match '^\s*(\S+)\s+(beacon-\d{2})\s*$') {
            [void]$ids.Add($Matches[1])
        }
    }

    $ids | Select-Object -Unique
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

function Get-ContainerName([string]$ContainerId) {
    $n = docker inspect --format '{{.Name}}' $ContainerId 2>$null
    "$n" -replace '^/', ''
}

function Show-Qdisc([string]$ContainerId) {
    $out = docker exec $ContainerId tc qdisc show dev eth0 2>$null
    if (-not $out) { return '' }
    (@($out) -join ' ')
}

function Set-Qdisc([string]$ContainerId, [string]$QdiscArgs) {
    $qargs = $QdiscArgs -split '\s+'
    docker exec $ContainerId tc qdisc replace dev eth0 root netem @qargs | Out-Null
}

function Clear-Qdisc([string]$ContainerId) {
    docker exec $ContainerId tc qdisc del dev eth0 root 2>$null | Out-Null
}

function Infer-Mode([string[]]$Containers) {
    if ($Containers.Count -eq 0) { return 'unavailable' }
    $starlink = 0; $degraded = 0; $direct = 0; $custom = 0
    foreach ($cid in $Containers) {
        $q = Show-Qdisc $cid
        if ($q -notmatch 'netem') { $direct++; continue }
        if ($q -match 'loss 0\.8%' -and $q -match 'rate 150Mbit') { $starlink++ }
        elseif ($q -match 'loss 3%' -and $q -match 'rate 50Mbit') { $degraded++ }
        else { $custom++ }
    }
    $total = $Containers.Count
    if ($starlink -eq $total) { return 'starlink' }
    if ($degraded -eq $total) { return 'degraded' }
    if ($direct   -eq $total) { return 'direct' }
    'mixed'
}

function Write-StatusFile([string]$ModeValue, [int]$ContainerCount) {
    $now   = Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz'
    $ssids = (Get-ActiveSsids) -join ','
    $content = @"
mode=$ModeValue
updated_at=$now
source=$Source
target_ssid=$TargetSsid
active_ssids=$ssids
container_count=$ContainerCount
"@
    # UTF-8 without BOM so Python's utf-8 reader doesn't see ﻿ on the first key.
    [System.IO.File]::WriteAllText($StatusFile, $content, (New-Object System.Text.UTF8Encoding($false)))
}

$containers = @(Get-BeaconContainers)

if ($containers.Count -eq 0 -and $Mode -ne 'status') {
    Write-StatusFile -ModeValue 'unavailable' -ContainerCount 0
    Write-Host 'No beacon containers are running. Start them with: docker compose up -d'
    exit 1
}

switch ($Mode) {
    'starlink' {
        Write-Host "Applying Starlink tc profile to $($containers.Count) beacon containers..."
        foreach ($c in $containers) { Set-Qdisc $c $StarlinkQdisc }
        $effective = 'starlink'
    }
    'degraded' {
        Write-Host "Applying degraded Starlink tc profile to $($containers.Count) beacon containers..."
        foreach ($c in $containers) { Set-Qdisc $c $DegradedQdisc }
        $effective = 'degraded'
    }
    { $_ -in 'direct', 'clear' } {
        Write-Host "Clearing tc profile from $($containers.Count) beacon containers..."
        foreach ($c in $containers) { Clear-Qdisc $c }
        $effective = 'direct'
    }
    'status' {
        $effective = Infer-Mode $containers
    }
}

Write-StatusFile -ModeValue $effective -ContainerCount $containers.Count

Write-Host "Mode: $effective"
Write-Host "Target SSID: $TargetSsid"
Write-Host "Active SSIDs: $((Get-ActiveSsids) -join ',')"
Write-Host "Containers: $($containers.Count)"
foreach ($c in $containers) {
    $name = Get-ContainerName $c
    $q    = Show-Qdisc $c
    Write-Host "- ${name}: $q"
}
