$ErrorActionPreference = 'Stop'
$facts = New-Object System.Collections.Generic.List[object]

function Add-Fact {
  param([string]$Id, [object]$Value, [string]$Type = $null)
  $facts.Add([pscustomobject]@{ id=$Id; value=$Value; type=$Type })
}

$profileNames = @{ 1='Domain'; 2='Private'; 4='Public' }
function Profile-Name([int]$mask){ foreach($k in $profileNames.Keys){ if(($mask -band $k) -ne 0){ return $profileNames[$k] } } }

$fw = New-Object -ComObject HNetCfg.FwPolicy2

foreach ($kv in $profileNames.GetEnumerator()) {
  $mask = [int]$kv.Key; $name = $kv.Value
  Add-Fact "win.firewall.$name.enabled" ($fw.FirewallEnabled($mask)) 'bool'
  $in  = if ($fw.DefaultInboundAction($mask)  -eq 1) {'Block'} else {'Allow'}
  $out = if ($fw.DefaultOutboundAction($mask) -eq 1) {'Block'} else {'Allow'}
  Add-Fact "win.firewall.$name.default_inbound"  $in  'string'
  Add-Fact "win.firewall.$name.default_outbound" $out 'string'
  $notifEnabled = -not ($fw.NotificationsDisabled($mask))
  Add-Fact "win.firewall.$name.notifications" $notifEnabled 'bool'
}

$rules = @($fw.Rules)
$enabledRules = $rules | Where-Object { $_.Enabled }

$inboundAllow = $enabledRules | Where-Object { $_.Direction -eq 1 -and $_.Action -eq 1 }
$inboundBlock = $enabledRules | Where-Object { $_.Direction -eq 1 -and $_.Action -eq 0 }
Add-Fact "win.firewall.rules.enabled_count"         $enabledRules.Count 'int'
Add-Fact "win.firewall.inbound_allow_enabled_count" $inboundAllow.Count 'int'
Add-Fact "win.firewall.inbound_block_enabled_count" $inboundBlock.Count 'int'

function Has-Allow($group, [int]$mask) {
  $match = $enabledRules | Where-Object {
    $_.Direction -eq 1 -and $_.Action -eq 1 -and
    ($_.Profiles -band $mask) -ne 0 -and
    ($_.Grouping -like "*$group*")
  } | Select-Object -First 1
  if ($null -ne $match) { $true } else { $false }
}

foreach ($kv in $profileNames.GetEnumerator()) {
  $mask = [int]$kv.Key; $name = $kv.Value
  Add-Fact "win.firewall.$name.inbound_allow_rdp"   (Has-Allow 'Remote Desktop'            $mask) 'bool'
  Add-Fact "win.firewall.$name.inbound_allow_smb"   (Has-Allow 'File and Printer Sharing'  $mask) 'bool'
  Add-Fact "win.firewall.$name.inbound_allow_winrm" (Has-Allow 'Windows Remote Management' $mask) 'bool'
}

$hostname = $env:COMPUTERNAME
[pscustomobject]@{
  collector    = "win_firewall"
  hostname     = $hostname
  host         = @{ hostname = $hostname }
  collected_at = (Get-Date).ToUniversalTime().ToString("s") + "Z"
  facts        = $facts
} | ConvertTo-Json -Depth 5 -Compress
