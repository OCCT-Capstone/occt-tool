import json, os, sys, subprocess, datetime, re

def iso_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def fact_bool(fid, v): return {"id": fid, "type":"bool", "value": bool(v)}
def fact_int(fid, v):  return {"id": fid, "type":"int",  "value": int(v)}
def fact_str(fid, v):  return {"id": fid, "type":"string","value": str(v)}

def run(cmd, timeout=25):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd} failed: {p.stderr.strip()}")
    return p.stdout

def pwsh(ps, timeout=25):
    ps_path = os.environ.get("OCCT_PWSH", r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    return run([ps_path, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=timeout)

def secedit_export(tmp_path):
    out = run(["secedit", "/export", "/cfg", tmp_path], timeout=20)
    with open(tmp_path, "r", encoding="utf-16") as f:
        lines = f.readlines()
    kv = {}
    for line in lines:
        m = re.match(r"^\s*([^;][^=]+?)\s*=\s*(.*)\s*$", line)
        if m:
            kv[m.group(1).strip()] = m.group(2).strip()
    return kv

def get_wevtutil_gl(channel="Security"):
    out = run(["wevtutil", "gl", channel], timeout=10)
    bytes_size = None; retention = None
    for line in out.splitlines():
        if "maxSize:" in line:
            try: bytes_size = int(line.split("maxSize:")[1].strip())
            except: pass
        if "retention:" in line:
            retention = line.split("retention:")[1].strip().lower() == "true"
    return bytes_size, retention

def icacls_security_writers():
    path = r"C:\Windows\System32\winevt\Logs\Security.evtx"
    out = run(["icacls", path], timeout=10)
    allow = {
        r"NT AUTHORITY\SYSTEM",
        r"BUILTIN\Administrators",
        r"NT SERVICE\EventLog",
        r"NT AUTHORITY\LOCAL SERVICE",
    }
    offenders = 0
    checked = False
    for line in out.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("processed"): continue
        parts = line.split(":")
        if len(parts) < 2: continue
        ident = parts[0].strip()
        rights = parts[1]
        tokens = [t for t in re.findall(r"\([A-Z]+\)", rights) if t != "(I)"]
        write_like = any(t in tokens for t in ["(F)","(M)","(W)"])
        if write_like:
            checked = True
            if ident not in allow:
                offenders += 1
    return offenders, checked

def time_service_facts():
    # service state + start type
    svc = pwsh("Get-Service w32time | Select-Object -ExpandProperty Status").strip()
    start_type = pwsh("(Get-Service w32time).StartType.ToString()").strip()

    # Query both configuration and status once
    cfg    = run(["w32tm", "/query", "/configuration"], timeout=10)
    status = run(["w32tm", "/query", "/status"],        timeout=10)

    # peers configured?
    m_ntp = re.search(r"(?im)^\s*NtpServer:\s*(.+?)\s*$", cfg)
    ntp_raw = (m_ntp.group(1).strip() if m_ntp else "")
    ntp_configured = bool(ntp_raw and ntp_raw.lower() != "not configured")

    # source (from /status)
    src = "Unknown"
    m_src = re.search(r"(?im)^\s*Source:\s*(.+?)\s*$", status)
    if m_src:
        src = m_src.group(1).strip()

    # hours since last sync (let PowerShell parse the locale-specific date)
    try:
        ps = r"""
$line = (w32tm /query /status) -match 'Last Successful Sync Time'
if ($line) {
  $val = ($line -split ':',2)[1].Trim()
  [int]((Get-Date).ToUniversalTime().Subtract([datetime]::Parse($val).ToUniversalTime()).TotalHours)
} else { 9999 }
"""
        hours_since = int(pwsh(ps, timeout=10).strip())
    except Exception:
        hours_since = 9999

    return (svc.lower()=="running", start_type, src, hours_since, ntp_configured)


def admins_group_facts():
    base_allow = {
        r"BUILTIN\Administrators",
        r"NT AUTHORITY\SYSTEM",
        r"NT AUTHORITY\LOCAL SERVICE",
        r"NT AUTHORITY\NETWORK SERVICE",
        fr"{os.environ.get('COMPUTERNAME','')}\Administrator",
    }
    strict_allow = {
        r"BUILTIN\Administrators",
        r"NT AUTHORITY\SYSTEM",
        fr"{os.environ.get('COMPUTERNAME','')}\Administrator",
    }
    ps = "Get-LocalGroupMember -Group Administrators | ForEach-Object { $_.Name }"
    out = pwsh(ps)
    members = [x.strip() for x in out.splitlines() if x.strip()]
    unauth = [m for m in members if m not in base_allow]
    unauth_strict = [m for m in members if m not in strict_allow]
    return True, len(unauth), len(unauth_strict)

def _wmic_rid_enabled(sid_suffix):
    try:
        out = run(["wmic", "useraccount", "where", f"LocalAccount='TRUE' and SID like '%-{sid_suffix}'", "get", "Disabled", "/value"], timeout=8)
        m = re.search(r"(?i)Disabled=(True|False)", out)
        if not m: return None
        disabled = m.group(1).lower() == "true"
        return not disabled
    except Exception:
        return None

def _net_user_enabled(name):
    try:
        out = run(["net", "user", name], timeout=8)
        m = re.search(r"(?im)^\s*Account\s+active\s+(\S.+?)\s*(Yes|No)\s*$", out)
        if not m:
            m = re.search(r"(?im)^\s*Account\s+active\s*[:\. ]+\s*(Yes|No)\s*$", out)
        if not m: return None
        return m.group(m.lastindex).strip().lower() == "yes"
    except Exception:
        return None

def local_builtin_accounts():
    admin_enabled = None; guest_enabled = None
    try:
        ps = r"Get-LocalUser | Select-Object Name,Enabled,SID | ConvertTo-Json"
        out = pwsh(ps)
        arr = json.loads(out)
        if isinstance(arr, dict): arr=[arr]
        for u in arr:
            sid = str(u.get("SID",""))
            if sid.endswith("-500"): admin_enabled = bool(u.get("Enabled", False))
            if sid.endswith("-501"): guest_enabled = bool(u.get("Enabled", False))
    except Exception:
        pass
    if admin_enabled is None:
        admin_enabled = _wmic_rid_enabled("500")
    if guest_enabled is None:
        guest_enabled = _wmic_rid_enabled("501")
    if admin_enabled is None:
        admin_enabled = _net_user_enabled("Administrator")
    if guest_enabled is None:
        guest_enabled = _net_user_enabled("Guest")
    return admin_enabled, guest_enabled

def sample_event_keyfields():
    try:
        ps = r"""
$ev = Get-WinEvent -LogName Security -MaxEvents 10 | Select-Object -First 5
$ok = $false
foreach($e in $ev){
  $id = $e.Id
  $t  = $e.TimeCreated
  $m  = $e | Format-List -Property * | Out-String
  if($id -and $t -and ($m -match 'TargetUserName')){ $ok = $true; break }
}
$ok
"""
        out = pwsh(ps, timeout=10).strip().lower()
        return out == "true"
    except Exception:
        return False

def main():
    if os.name != "nt":
        print(json.dumps({"error": "windows_only"})); return
    facts = []
    hostname = os.environ.get("COMPUTERNAME","")
    pw_min_len = pw_complex = pw_max_age = pw_min_age = pw_hist = 0
    lock_threshold = lock_duration = lock_reset = 0
    try:
        tmp = os.path.join(os.environ.get("TEMP","."), "secpol.cfg")
        kv = secedit_export(tmp)
        pw_min_len = int(kv.get("MinimumPasswordLength","0") or "0")
        pw_complex = kv.get("PasswordComplexity","0") in ("1","true","True")
        pw_max_age = int(kv.get("MaximumPasswordAge","0") or "0")
        pw_min_age = int(kv.get("MinimumPasswordAge","0") or "0")
        pw_hist    = int(kv.get("PasswordHistorySize","0") or "0")
        lock_threshold = int(kv.get("LockoutBadCount","0") or "0")
        lock_duration  = int(kv.get("LockoutDuration","0") or "0")
        lock_reset     = int(kv.get("ResetLockoutCount","0") or "0")
    except Exception:
        na = run(["net","accounts"], timeout=8)
        def m(rx):
            mm = re.search(rx, na)
            return mm.group(1) if mm else "0"
        pw_min_len = int(m(r"Minimum password length\s*:\s*(\d+)"))
        pw_max_age = int(m(r"Maximum password age\s*:\s*(\d+)"))
        pw_min_age = int(m(r"Minimum password age\s*:\s*(\d+)"))
        pw_hist    = int(m(r"Password history length\s*:\s*(\d+)"))
        lock_threshold = int(m(r"Lockout threshold\s*:\s*(\d+)"))
        lock_duration  = int(m(r"Lockout duration\s*:\s*(\d+)"))
        lock_reset     = int(m(r"Lockout observation window\s*:\s*(\d+)"))
        pw_complex = False
    facts += [
        fact_int ("win.pw.min_length", pw_min_len),
        fact_bool("win.pw.complexity_required", pw_complex),
        fact_int ("win.pw.max_age_days", pw_max_age),
        fact_int ("win.pw.min_age_days", pw_min_age),
        fact_int ("win.pw.history_size", pw_hist),
        fact_int ("win.lockout.threshold", lock_threshold),
        fact_int ("win.lockout.duration_minutes", lock_duration),
        fact_int ("win.lockout.reset_minutes", lock_reset),
    ]
    bytes_size, retention = get_wevtutil_gl("Security")
    size_mb = int((bytes_size or 0) // (1024*1024))
    facts += [
        fact_int ("win.evtx.security.max_size_mb", size_mb),
        fact_bool("win.evtx.security.retention_enabled", bool(retention)),
    ]
    offenders, checked = icacls_security_writers()
    facts += [
        fact_bool("win.evtx.security.acl_checked", checked),
        fact_int ("win.evtx.security.write_offender_count", offenders),
    ]
    running, start_type, source, hours_since, ntp_configured = time_service_facts()
    facts += [
        fact_bool("win.time.service_running", running),
        fact_str ("win.time.start_type", start_type),
        fact_str ("win.time.source", source),
        fact_int ("win.time.hours_since_last_sync", hours_since),
        fact_bool("win.time.ntp_configured", ntp_configured),
    ]
    admin_enabled, guest_enabled = local_builtin_accounts()
    if admin_enabled is not None:
        facts += [fact_bool("win.local.admin500_enabled", admin_enabled)]
    if guest_enabled is not None:
        facts += [fact_bool("win.local.guest501_enabled", guest_enabled)]
    admins_checked, unauth_cnt, unauth_cnt_strict = admins_group_facts()
    facts += [
        fact_bool("win.admins.checked", admins_checked),
        fact_int ("win.admins.unauthorized_count", unauth_cnt),
        fact_int ("win.admins.unauthorized_count_strict", unauth_cnt_strict),
    ]
    facts += [fact_bool("win.evtx.security.sample_has_key_fields", sample_event_keyfields())]
    doc = {
        "collector": "win_host",
        "host": {"hostname": os.environ.get("COMPUTERNAME","")},
        "collected_at": iso_now(),
        "facts": facts
    }
    print(json.dumps(doc, ensure_ascii=False))

if __name__ == "__main__":
    main()
