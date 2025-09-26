<#
  OCCT – Windows Firewall facts collector
  Emits a single JSON document to STDOUT (no Write-Host banners).

  Facts produced (examples):
    win.firewall.Domain.enabled                  (bool)
    win.firewall.Domain.default_inbound          (string: Block|Allow)
    win.firewall.Domain.default_outbound         (string)
    win.firewall.Domain.notifications            (bool: notifications shown)
    win.firewall.rules.enabled_count             (int)
    win.firewall.inbound_allow_enabled_count     (int)
    win.firewall.inbound_block_enabled_count     (int)
    win.firewall.Domain.inbound_allow_rdp        (bool)
    win.firewall.Private.inbound_allow_smb       (bool)
    win.firewall.Public.inbound_allow_winrm      (bool)
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-NowIsoUtc {
  (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
}

function New-BoolFact {
  param([Parameter(Mandatory)][string]$Id, [Parameter(Mandatory)][bool]$Value)
  [pscustomobject]@{ id = $Id; type = "bool"; value = $Value }
}
function New-StrFact {
  param([Parameter(Mandatory)][string]$Id, [Parameter(Mandatory)][string]$Value)
  [pscustomobject]@{ id = $Id; type = "string"; value = $Value }
}
function New-IntFact {
  param([Parameter(Mandatory)][string]$Id, [Parameter(Mandatory)][int]$Value)
  [pscustomobject]@{ id = $Id; type = "int"; value = $Value }
}

# ----- Gather profile-level settings -----
$profiles = Get-NetFirewallProfile
$profileMap = @{
  Domain  = ($profiles | Where-Object Name -eq 'Domain'  | Select-Object -First 1)
  Private = ($profiles | Where-Object Name -eq 'Private' | Select-Object -First 1)
  Public  = ($profiles | Where-Object Name -eq 'Public'  | Select-Object -First 1)
}

$facts = New-Object System.Collections.Generic.List[object]

foreach ($pname in @('Domain','Private','Public')) {
  $p = $profileMap[$pname]
  if ($null -eq $p) { continue }

  # Enabled
  $facts.Add((New-BoolFact "win.firewall.$pname.enabled" ([bool]$p.Enabled)))

  # Default actions
  $facts.Add((New-StrFact  "win.firewall.$pname.default_inbound"  ([string]$p.DefaultInboundAction)))
  $facts.Add((New-StrFact  "win.firewall.$pname.default_outbound" ([string]$p.DefaultOutboundAction)))

  # Notifications (true means notifications shown)
  $facts.Add((New-BoolFact "win.firewall.$pname.notifications" ([bool](-not $p.NotificationsDisabled))))
}

# ----- Rule inventory (enabled only) -----
$enabledRules = @( Get-NetFirewallRule -Enabled True -ErrorAction SilentlyContinue )
$facts.Add((New-IntFact "win.firewall.rules.enabled_count" ($enabledRules.Count)))

# Split inbound allow/block
$inAllow = @($enabledRules | Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Allow' })
$inBlock = @($enabledRules | Where-Object { $_.Direction -eq 'Inbound' -and $_.Action -eq 'Block' })
$facts.Add((New-IntFact "win.firewall.inbound_allow_enabled_count" ($inAllow.Count)))
$facts.Add((New-IntFact "win.firewall.inbound_block_enabled_count" ($inBlock.Count)))

# ----- Join filters (port/address) for inbound allow rules -----
$portFilters = @()
if ($inAllow.Count -gt 0) {
  $portFilters = $inAllow | Get-NetFirewallPortFilter -ErrorAction SilentlyContinue
}
$addrFilters = @()
if ($inAllow.Count -gt 0) {
  $addrFilters = $inAllow | Get-NetFirewallAddressFilter -ErrorAction SilentlyContinue
}

# Quick lookup by InstanceID (InstanceID matches Rule.InstanceID)
$portsById = @{}
foreach ($pf in $portFilters) { $portsById[$pf.InstanceID] = $pf }
$addrById  = @{}
foreach ($af in $addrFilters) { $addrById[$af.InstanceID]  = $af }

# ----- Helpers for profile bitmask + effective openness -----
function Test-RuleUsesProfile {
  param([Parameter(Mandatory)][uint32]$ProfileMask, [Parameter(Mandatory)][string]$ProfileName)
  switch ($ProfileName) {
    'Domain'  { return (($ProfileMask -band 1) -ne 0) -or ($ProfileMask -eq 0) }  # 0 = All
    'Private' { return (($ProfileMask -band 2) -ne 0) -or ($ProfileMask -eq 0) }
    'Public'  { return (($ProfileMask -band 4) -ne 0) -or ($ProfileMask -eq 0) }
    default   { return $false }
  }
}

function Test-AnyOpenForProfile {
  param(
    [Parameter(Mandatory)][System.Collections.IEnumerable]$Rules,
    [Parameter(Mandatory)][int[]]$Ports,
    [Parameter(Mandatory)][string]$ProfileName
  )
  foreach ($r in $Rules) {
    if (-not (Test-RuleUsesProfile -ProfileMask ([uint32]$r.Profile) -ProfileName $ProfileName)) { continue }

    $pf = $portsById[$r.InstanceID]
    if ($null -eq $pf) { continue }

    # LocalPort may be 'Any', a number, or a comma list
    $lp = [string]$pf.LocalPort
    $portMatch = $false
    if ([string]::IsNullOrWhiteSpace($lp) -or $lp -eq 'Any') {
      $portMatch = $true
    } else {
      $lpList = $lp -split ',' | ForEach-Object { $_.Trim() }
      foreach ($p in $Ports) {
        if ($lpList -contains "$p") { $portMatch = $true; break }
      }
    }
    if (-not $portMatch) { continue }

    # RemoteAddress: treat Any or blank as open exposure
    $af = $addrById[$r.InstanceID]
    $ra = $af.RemoteAddress
    $openRemote = $false
    if ($null -eq $ra -or $ra -eq '' -or $ra -eq 'Any' -or ($ra -is [array] -and $ra.Count -eq 1 -and $ra[0] -eq 'Any')) {
      $openRemote = $true
    } else {
      # Prototype simplification: any explicit remote still considered "open"
      $openRemote = $true
    }

    if ($openRemote) { return $true }
  }
  return $false
}

# ----- Per-profile risky service exposure (Inbound Allow to "Any") -----
$rdpPorts   = @(3389)
$smbPorts   = @(139,445)
$winrmPorts = @(5985,5986)

foreach ($pname in @('Domain','Private','Public')) {
  $facts.Add((New-BoolFact "win.firewall.$pname.inbound_allow_rdp"   (Test-AnyOpenForProfile -Rules $inAllow -Ports $rdpPorts   -ProfileName $pname)))
  $facts.Add((New-BoolFact "win.firewall.$pname.inbound_allow_smb"   (Test-AnyOpenForProfile -Rules $inAllow -Ports $smbPorts   -ProfileName $pname)))
  $facts.Add((New-BoolFact "win.firewall.$pname.inbound_allow_winrm" (Test-AnyOpenForProfile -Rules $inAllow -Ports $winrmPorts -ProfileName $pname)))
}

# ----- Emit JSON to STDOUT -----
$result = [pscustomobject]@{
  collector    = "win_firewall"
  host         = @{ hostname = $env:COMPUTERNAME }
  collected_at = Get-NowIsoUtc
  facts        = $facts
}

$result | ConvertTo-Json -Depth 6
