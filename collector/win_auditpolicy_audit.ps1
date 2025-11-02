Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-NowIsoUtc { (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }
function New-BoolFact { param([Parameter(Mandatory)][string]$Id,[Parameter(Mandatory)][bool]$Value) [pscustomobject]@{id=$Id;type="bool";value=$Value} }
function New-StrFact  { param([Parameter(Mandatory)][string]$Id,[Parameter(Mandatory)][string]$Value) [pscustomobject]@{id=$Id;type="string";value=$Value} }
function NormalizeName { param([Parameter(Mandatory)][string]$s) ($s -replace '[^A-Za-z0-9]+','_').Trim('_').ToLower() }
function Invoke-Native {
  param([Parameter(Mandatory)][string]$File,[Parameter()][string[]]$Args)
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = $File
  $psi.Arguments = [string]::Join(' ', $Args)
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.CreateNoWindow = $true
  $p = New-Object System.Diagnostics.Process
  $p.StartInfo = $psi
  [void]$p.Start()
  $stdout = $p.StandardOutput.ReadToEnd()
  $stderr = $p.StandardError.ReadToEnd()
  $p.WaitForExit()
  [pscustomobject]@{ ExitCode=$p.ExitCode; StdOut=$stdout; StdErr=$stderr }
}

$facts = New-Object System.Collections.Generic.List[object]
$ap = Join-Path $env:WINDIR "System32\auditpol.exe"

$want = @(
  'Logon',
  'User Account Management',
  'Security Group Management',
  'Audit Policy Change',
  'Account Lockout'
)

$aliases = @{
  'logon'                     = 'Logon'
  'user_account_management'   = 'UserAccountManagement'
  'security_group_management' = 'SecurityGroupManagement'
  'audit_policy_change'       = 'AuditPolicyChange'
  'account_lockout'           = 'AccountLockout'
}

$agg = @{}
$names = Invoke-Native $ap @('/list','/subcategory:*')
$subs = @()
if ($names.ExitCode -eq 0 -and -not [string]::IsNullOrWhiteSpace($names.StdOut)) {
  $subs = $names.StdOut -split "`r?`n" | Where-Object { $_ -match '\S' } | ForEach-Object { $_.Trim() } | Sort-Object -Unique
} else {
  $subs = $want
}

foreach ($s in $subs) {
  $g = Invoke-Native $ap @('/get',("/subcategory:`"{0}`"" -f $s))
  if ($g.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($g.StdOut)) { continue }
  $glines = $g.StdOut -split "`r?`n" | Where-Object { $_ -match '^\s{2,}.+?\s{2,}.+$' }
  foreach ($line in $glines) {
    if ($line -match '^\s{2,}(.+?)\s{2,}(.+?)\s*$') {
      $sub = $Matches[1].Trim()
      $setting = $Matches[2].Trim()
      $subNorm = NormalizeName $sub
      $succ = ($setting -match 'Success')
      $fail = ($setting -match 'Failure')
      $facts.Add((New-BoolFact ("win.audit.{0}.success_enabled" -f $subNorm) $succ))
      $facts.Add((New-BoolFact ("win.audit.{0}.failure_enabled" -f $subNorm) $fail))
      $val = if ($succ -and $fail) { 'Success,Failure' } elseif ($succ) { 'Success' } elseif ($fail) { 'Failure' } else { 'NoAuditing' }
      $norm = NormalizeName $sub
      if ($aliases.ContainsKey($norm)) { $agg[$aliases[$norm]] = $val }
    }
  }
}

foreach ($k in $agg.Keys) {
  $facts.Add((New-StrFact ("win.audit.{0}" -f $k) $agg[$k]))
}

$advVal = $false
$coafVal = $false
try {
  $lsa = Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' -ErrorAction Stop
  if ($null -ne $lsa.SCENoApplyLegacyAuditPolicy) { if ([int]$lsa.SCENoApplyLegacyAuditPolicy -eq 1) { $advVal = $true } }
  if ($null -ne $lsa.CrashOnAuditFail) { if ([int]$lsa.CrashOnAuditFail -ge 1) { $coafVal = $true } }
} catch {}
$facts.Add((New-BoolFact 'win.audit.AdvancedAuditingEnabled' $advVal))
$facts.Add((New-BoolFact 'win.audit.CrashOnAuditFail' $coafVal))


$result = [pscustomobject]@{
  collector    = "win_auditpolicy"
  host         = @{ hostname = $env:COMPUTERNAME }
  collected_at = Get-NowIsoUtc
  facts        = $facts
}
$result | ConvertTo-Json -Depth 6
