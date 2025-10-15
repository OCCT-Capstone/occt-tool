Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function NowIsoUtc { (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }
function New-StrFact($id, [string]$value){ [pscustomobject]@{ id=$id; type="string"; value=$value } }
function New-BoolFact($id, [bool]$value){ [pscustomobject]@{ id=$id; type="bool";   value=$value } }

$need = @("Logon","Security Group Management","User Account Management","Account Lockout","Audit Policy Change")
$ap = & auditpol /get /subcategory:($need -join '","') 2>$null

$facts = New-Object System.Collections.Generic.List[object]
$map = @{
  "Logon"                     = "win.audit.Logon"
  "Security Group Management" = "win.audit.SecurityGroupManagement"
  "User Account Management"   = "win.audit.UserAccountManagement"
  "Account Lockout"           = "win.audit.AccountLockout"
  "Audit Policy Change"       = "win.audit.AuditPolicyChange"
}
foreach ($line in ($ap -split "`r?`n")) {
  if ($line -match "^\s*(Logon|Security Group Management|User Account Management|Account Lockout|Audit Policy Change)\s+(Success|Failure|No Auditing|Success, Failure|Success,Failure)\s*$") {
    $sub = $matches[1].Trim()
    $val = $matches[2].Replace("Success, Failure","Success,Failure")
    $facts.Add((New-StrFact $map[$sub] $val))
  }
}
$adv = ($facts | Where-Object { $_.value -match "Success|Failure" }).Count -gt 0
$facts.Add((New-BoolFact "win.audit.AdvancedAuditingEnabled" $adv))

# --- Crash on audit fail (FAU_STG.4) ---
$crashOnAuditFail = $false
try {
    $val = Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' -Name 'CrashOnAuditFail' -ErrorAction SilentlyContinue
    if ($null -ne $val -and $val.CrashOnAuditFail -eq 1) { $crashOnAuditFail = $true }
} catch { }

# Add to your facts object (example shape)
$facts.win.audit.CrashOnAuditFail = $crashOnAuditFail


[pscustomobject]@{
  collector    = "win_auditpolicy"
  host         = @{ hostname = $env:COMPUTERNAME }
  collected_at = NowIsoUtc
  facts        = $facts
} | ConvertTo-Json -Depth 6
