<#  collector/win_pwpolicy_facts.ps1
    Robust facts collector for Windows password policy.
    - Tries `secedit /export` (best) when elevated.
    - Falls back to `net accounts` + registry (works non-admin).
    - Emits ONLY JSON to STDOUT.
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

function Try-ExportSecPol {
    param([string]$Path)
    try {
        $global:LASTEXITCODE = $null
        & secedit /export /cfg $Path 1>$null 2>$null
        if (($LASTEXITCODE -is [int]) -and $LASTEXITCODE -ne 0) { return $false }
        return (Test-Path -LiteralPath $Path)
    } catch { return $false }
}

function Read-InfKeyValues {
    param([string]$Path)
    $map = @{}
    if (!(Test-Path -LiteralPath $Path)) { return $map }
    foreach ($line in (Get-Content -LiteralPath $Path)) {
        $ln = $line.Trim()
        if ($ln -match '^\s*[#;]') { continue }
        if ($ln -notmatch '=')     { continue }
        $parts = $ln -split '=', 2
        if ($parts.Count -eq 2) {
            $map[$parts[0].Trim()] = $parts[1].Trim()
        }
    }
    return $map
}

function Parse-NetAccounts {
    # Returns ordered hashtable with { MinLength, LockoutThreshold }
    $out = [ordered]@{ MinLength = $null; LockoutThreshold = $null }
    try {
        # Use -Stream to preserve lines w/out extra formatting
        $lines = net accounts 2>$null
        foreach ($line in $lines) {
            # Normalize spacing for regex friendliness
            $ln = ($line -replace '\s+', ' ').Trim()

            # Examples we need to match:
            # "Minimum password length (0 = unlimited): 14"
            # "Minimum password length : 14"
            if ($ln -match '(?i)Minimum password length.*?:\s*(\d+)') {
                $out.MinLength = [int]$Matches[1]
            }

            # Examples:
            # "Lockout threshold: Never"
            # "Account lockout threshold: 5"
            if ($ln -match '(?i)\b(?:Account\s+)?Lockout threshold\b.*?:\s*(Never|\d+)') {
                $val = $Matches[1]
                if ($val -eq 'Never') {
                    $out.LockoutThreshold = 0
                } else {
                    $out.LockoutThreshold = [int]$val
                }
            }
        }
    } catch {
        # ignore; fallbacks handle nulls
    }
    return $out
}


function Read-PasswordComplexity {
    # HKLM\SYSTEM\CurrentControlSet\Control\Lsa\PasswordComplexity (DWORD 0/1)
    try {
        $v = (Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' -Name 'PasswordComplexity' -ErrorAction SilentlyContinue).PasswordComplexity
        if ($null -ne $v) { return [bool]([int]$v) }
    } catch { }
    return $false
}

function Get-PasswordPolicy {
    $result = [ordered]@{
        MinimumPasswordLength = $null
        PasswordComplexity    = $null
        LockoutThreshold      = $null
        Source                = @()
    }

    # --- Try secedit export first (best fidelity) ---
    $tmp = Join-Path $env:TEMP ("secpol_{0}.inf" -f ([guid]::NewGuid().ToString('N')))
    try {
        if (Try-ExportSecPol -Path $tmp) {
            $cfg = Read-InfKeyValues -Path $tmp

            $minLen  = 0;  [void][int]::TryParse($cfg['MinimumPasswordLength'], [ref]$minLen)
            $complex = ($cfg['PasswordComplexity'] -eq '1')
            $lockBad = 0;  [void][int]::TryParse($cfg['LockoutBadCount'], [ref]$lockBad)

            $result.MinimumPasswordLength = $minLen
            $result.PasswordComplexity    = $complex
            $result.LockoutThreshold      = $lockBad
            $result.Source += 'secedit'
        }
    } finally {
        if (Test-Path -LiteralPath $tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue }
    }

    # --- Fallbacks (non-admin path) ---
    # Min length + lockout threshold via `net accounts`
    if ($null -eq $result.MinimumPasswordLength -or $result.MinimumPasswordLength -eq 0 -or
        $null -eq $result.LockoutThreshold) {

        $na = Parse-NetAccounts
        if ($null -eq $result.MinimumPasswordLength -or $result.MinimumPasswordLength -eq 0) {
            if ($null -ne $na.MinLength) {
                $result.MinimumPasswordLength = [int]$na.MinLength
                $result.Source += 'net accounts:min_length'
            }
        }
        if ($null -eq $result.LockoutThreshold) {
            if ($null -ne $na.LockoutThreshold) {
                $result.LockoutThreshold = [int]$na.LockoutThreshold
                $result.Source += 'net accounts:lockout_threshold'
            }
        }
    }

    # Complexity from registry (works without admin)
    if ($null -eq $result.PasswordComplexity) {
        $result.PasswordComplexity = Read-PasswordComplexity
        $result.Source += 'registry:PasswordComplexity'
    }

    # Final safety defaults
    if ($null -eq $result.MinimumPasswordLength) { $result.MinimumPasswordLength = 0 }
    if ($null -eq $result.LockoutThreshold)      { $result.LockoutThreshold = 0 }
    if ($null -eq $result.PasswordComplexity)    { $result.PasswordComplexity = $false }

    return [pscustomobject]$result
}

# --- Main -----------------------------------------------------------------
try {
    $policy   = Get-PasswordPolicy
    $now      = (Get-Date).ToUniversalTime().ToString('s') + 'Z'
    $hostName = $env:COMPUTERNAME

    $facts = [pscustomobject]@{
        collector    = 'win_pwpolicy'
        host         = @{ hostname = $hostName }
        collected_at = $now
        facts        = @(
            @{ id='win.password.min_length';          type='int';  value=$policy.MinimumPasswordLength },
            @{ id='win.password.complexity_enabled';  type='bool'; value=$policy.PasswordComplexity },
            @{ id='win.password.lockout_threshold';   type='int';  value=$policy.LockoutThreshold }
        )
        meta         = @{ source = $policy.Source }   # optional for debugging
    }

    # IMPORTANT: emit ONLY JSON to STDOUT
    $facts | ConvertTo-Json -Depth 6
}
catch {
    # Don’t emit any non-JSON text; let the runner log exit code
    exit 1
}
