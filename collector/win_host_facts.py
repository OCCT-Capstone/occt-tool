#!/usr/bin/env python3
# OCCT – Windows host compliance facts (Python collector)
# Emits JSON to STDOUT with: {collector, host, collected_at, facts:[{id,type,value}, ...]}

import json, os, sys, subprocess, datetime, shutil, re

def iso_now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def fact_bool(fid, v): return {"id": fid, "type":"bool", "value": bool(v)}
def fact_int(fid, v):  return {"id": fid, "type":"int",  "value": int(v)}
def fact_str(fid, v):  return {"id": fid, "type":"string","value": str(v)}

def run(cmd, timeout=25):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd} failed: {p.stderr.strip()}")
    return p.stdout

def pwsh(ps, timeout=25):
    # Use Windows PowerShell for widest compatibility
    ps_path = os.environ.get("OCCT_PWSH", r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    return run([ps_path, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=timeout)

def secedit_export(tmp_path):
    run(["secedit", "/export", "/cfg", tmp_path], timeout=20)
    # UTF-16 LE text; parse minimal keys we need
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
    # parse: maxSize: 134217728   retention: true/false
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
    # allow-list identities with write-like rights
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
        # Format: <Identity>:(I)(F) or (M)/(W)/...
        parts = line.split(":")
        if len(parts) < 2: continue
        ident = parts[0].strip()
        rights = parts[1]
        # remove (I) tokens
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
    # source and last successful sync
    cfg = run(["w32tm", "/query", "/configuration"], timeout=10)
    src = "Unknown"
    for line in cfg.splitlines():
        if "Source:" in line:
            src = line.split("Source:")[1].strip()
            break
    status = run(["w32tm", "/query", "/status"], timeout=10)
    last = None
    for line in status.splitlines():
        if "Last Successful Sync Time" in line:
            last = line.split(":",1)[1].strip()
            break
    hours_since = 9999
    if last:
        # normalize via PowerShell to handle locale
        iso = pwsh(f"[datetime]::Parse('{last}').ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')").strip()
        try:
            dt = datetime.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ")
            hours_since = int((datetime.datetime.utcnow()-dt).total_seconds()//3600)
        except: pass
    return (svc.lower()=="running", start_type, src, hours_since)

def admins_group_offenders():
    # list local Administrators members; compare to allowlist
    allow = {
        r"BUILTIN\Administrators",
        r"NT AUTHORITY\SYSTEM",
        r"NT AUTHORITY\LOCAL SERVICE",
        r"NT AUTHORITY\NETWORK SERVICE",
        fr"{os.environ.get('COMPUTERNAME','')}\Administrator",
    }
    ps = "Get-LocalGroupMember -Group Administrators | ForEach-Object { $_.Name }"
    out = pwsh(ps)
    members = [x.strip() for x in out.splitlines() if x.strip()]
    offenders = [m for m in members if m not in allow]
    return len(offenders), True

def local_builtin_accounts():
    # RID 500 admin & 501 guest Enabled flags
    ps = r"Get-LocalUser | Select-Object Name,Enabled,SID | ConvertTo-Json"
    out = pwsh(ps)
    try:
        arr = json.loads(out)
        if isinstance(arr, dict): arr=[arr]
    except:
        arr=[]
    admin_enabled = None; guest_enabled = None
    for u in arr:
        sid = str(u.get("SID",""))
        if sid.endswith("-500"): admin_enabled = bool(u.get("Enabled", False))
        if sid.endswith("-501"): guest_enabled = bool(u.get("Enabled", False))
    return admin_enabled, guest_enabled

def sample_event_keyfields():
    # quick health check: do we see EventID, TimeCreated, TargetUserName in recent security events?
    # requires SeSecurityPrivilege/Admin; degrade gracefully
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

    # --- Password policy & lockout via secedit (with net accounts fallback) ---
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
        # fallback: net accounts (locale fragile, best-effort)
        na = run(["net","accounts"], timeout=8)
        def m(rx): 
            mm = re.search(rx, na); 
            return mm.group(1) if mm else "0"
        pw_min_len = int(m(r"Minimum password length\s*:\s*(\d+)"))
        pw_max_age = int(m(r"Maximum password age\s*:\s*(\d+)"))
        pw_min_age = int(m(r"Minimum password age\s*:\s*(\d+)"))
        pw_hist    = int(m(r"Password history length\s*:\s*(\d+)"))
        lock_threshold = int(m(r"Lockout threshold\s*:\s*(\d+)"))
        lock_duration  = int(m(r"Lockout duration\s*:\s*(\d+)"))
        lock_reset     = int(m(r"Lockout observation window\s*:\s*(\d+)"))
        pw_complex = False  # 'net accounts' doesn't expose this

    facts += [
        fact_int ("win.pw.min_length", pw_min_len),                 # FIA_SOS.1
        fact_bool("win.pw.complexity_required", pw_complex),        # FIA_SOS.1
        fact_int ("win.pw.max_age_days", pw_max_age),               # FIA_SOS.1
        fact_int ("win.pw.min_age_days", pw_min_age),               # FIA_SOS.2
        fact_int ("win.pw.history_size", pw_hist),                  # FIA_SOS.2
        fact_int ("win.lockout.threshold", lock_threshold),         # FIA_AFL.1 (context for AFL.2)
        fact_int ("win.lockout.duration_minutes", lock_duration),   # FIA_AFL.2
        fact_int ("win.lockout.reset_minutes", lock_reset),         # FIA_AFL.2
    ]

    # --- Security.evtx retention/size (FAU_SAR.1) ---
    bytes_size, retention = get_wevtutil_gl("Security")
    size_mb = int((bytes_size or 0) // (1024*1024))
    facts += [
        fact_int ("win.evtx.security.max_size_mb", size_mb),                # FAU_SAR.1
        fact_bool("win.evtx.security.retention_enabled", bool(retention)),  # FAU_SAR.1
    ]

    # --- Security.evtx ACL protection (FAU_STG.1) ---
    offenders, checked = icacls_security_writers()
    facts += [
        fact_bool("win.evtx.security.acl_checked", checked),                # FAU_STG.1 helper
        fact_int ("win.evtx.security.write_offender_count", offenders),     # FAU_STG.1
    ]

    # --- Time service (FPT_STM.1) ---
    running, start_type, source, hours_since = time_service_facts()
    facts += [
        fact_bool("win.time.service_running", running),                     # FPT_STM.1
        fact_str ("win.time.start_type", start_type),                       # FPT_STM.1
        fact_str ("win.time.source", source),                               # FPT_STM.1
        fact_int ("win.time.hours_since_last_sync", hours_since),           # FPT_STM.1
    ]

    # --- Local built-ins (FIA_UAU.1 / .2) ---
    admin_enabled, guest_enabled = local_builtin_accounts()
    if admin_enabled is not None:
        facts += [fact_bool("win.local.admin500_enabled", admin_enabled)]   # FIA_UAU.1
    if guest_enabled is not None:
        facts += [fact_bool("win.local.guest501_enabled", guest_enabled)]   # FIA_UAU.2

    # --- Log content has key fields (FAU_GEN.2 health check) ---
    facts += [fact_bool("win.evtx.security.sample_has_key_fields", sample_event_keyfields())]  # FAU_GEN.2-lite

    doc = {
        "collector": "win_host",
        "host": {"hostname": hostname},
        "collected_at": iso_now(),
        "facts": facts
    }
    print(json.dumps(doc, ensure_ascii=False))
    
if __name__ == "__main__":
    main()
