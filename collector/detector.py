# detector.py — Controls 1–3 + resilient detections
import subprocess, re, json, sys, os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# ---------- helpers ----------
def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{p.stderr.strip()}")
    return p.stdout

def iso_now():
    return datetime.now(timezone.utc).isoformat()

# ---------- Control #1: FIA_AFL.1 (lockout threshold) ----------
def chk_FIA_AFL_1():
    """Pass if account lockout threshold > 0. Try secedit, fallback net accounts."""
    try:
        run(["secedit", "/export", "/cfg", "secpol.cfg"])
        with open("secpol.cfg", encoding="utf-16-le", errors="ignore") as f:
            text = f.read()
        m = re.search(r"^LockoutBadCount\s*=\s*(\d+)", text, re.M)
        val = int(m.group(1)) if m else None
        if val is not None:
            return {
                "sfr":"FIA_AFL.1","control_id":"AU-002","title":"Account lockout threshold",
                "passed": val > 0,
                "evidence":{"source":"secedit","LockoutBadCount": val},
                "severity":"High"
            }
    except Exception:
        pass
    try:
        out = run(["net", "accounts"])
        m = re.search(r"Lockout\s*threshold\s*:\s*(\d+)", out, re.IGNORECASE)
        val = int(m.group(1)) if m else None
        return {
            "sfr":"FIA_AFL.1","control_id":"AU-002","title":"Account lockout threshold",
            "passed": (val is not None) and (val > 0),
            "evidence":{"source":"net accounts","LockoutThreshold": val},
            "severity":"High"
        }
    except Exception as e:
        return {
            "sfr":"FIA_AFL.1","control_id":"AU-002","title":"Account lockout threshold",
            "passed": False, "evidence":{"error": str(e)}, "severity":"High"
        }

# ---------- Control #2: FMT_SMR.1 (Admins membership minimal) ----------
def chk_FMT_SMR_1():
    """Pass if local Administrators group contains only an allow-list."""
    try:
        ps = "Get-LocalGroupMember Administrators | Select-Object -ExpandProperty Name"
        out = run(["powershell","-NoProfile","-Command", ps])
        members = [x.strip() for x in out.splitlines() if x.strip()]

        allow = {
            r"BUILTIN\\Administrators",
            r"NT AUTHORITY\\SYSTEM",
            rf"{os.environ.get('COMPUTERNAME','')}\\Administrator",
        }
        passed = all(m in allow for m in members)
        return {
            "sfr":"FMT_SMR.1","control_id":"AC-001","title":"Admins membership minimal",
            "passed": passed,
            "evidence":{"members": members, "allow_list": sorted(list(allow))},
            "severity":"High"
        }
    except Exception as e:
        return {
            "sfr":"FMT_SRM.1","control_id":"AC-001","title":"Admins membership minimal",
            "passed": False, "evidence":{"error": str(e)}, "severity":"High"
        }

# ---------- Control #3: FAU_GEN.1 (Audit policy configured) ----------
def chk_FAU_GEN_1():
    """
    Pass if required audit subcategories are enabled as specified.
    We check: Logon (S/F), Security Group Management (S/F), User Account Management (S/F),
    Account Lockout (S), Audit Policy Change (S/F).
    """
    required = {
        "Logon": {"Success", "Failure"},
        "Security Group Management": {"Success", "Failure"},
        "User Account Management": {"Success", "Failure"},
        "Account Lockout": {"Success"},
        "Audit Policy Change": {"Success", "Failure"},
    }

    def get_setting(name: str):
        try:
            out = run(["auditpol", "/get", f"/subcategory:{name}"])
            # e.g. "Logon                                 Success and Failure"
            m = re.search(rf"^\s*{re.escape(name)}\s+(.+)$", out, re.M)
            val = m.group(1).strip() if m else "Unknown"
            vs = set()
            if "Success" in val: vs.add("Success")
            if "Failure" in val: vs.add("Failure")
            return val, vs
        except Exception as e:
            return f"error: {e}", set()

    evidence = []
    all_ok = True
    for subcat, needed in required.items():
        raw, have = get_setting(subcat)
        ok = needed.issubset(have)
        all_ok &= ok
        evidence.append({
            "subcategory": subcat,
            "expected": sorted(list(needed)),
            "actual": raw,
            "meets_requirement": ok
        })

    return {
        "sfr": "FAU_GEN.1",
        "control_id": "AU-001",
        "title": "Audit policy configured",
        "passed": all_ok,
        "evidence": evidence,
        "severity": "High"
    }

# ---------- Control #4: FAU_SAR.1 (Audit log retention) ----------
def chk_FAU_SAR_1(min_mb: int = 128):
    """
    FAU_SAR.1 — Ensure audit (Security) log is retained sufficiently.
    Pass if retention is enabled OR max size >= min_mb.
    """
    try:
        out = run(["wevtutil", "gl", "Security"])
        # Example lines:
        #   maxSize: 209715200
        #   retention: false
        #   autoBackup: false
        #   enabled: true
        m_size = re.search(r"^\s*maxSize:\s*(\d+)\s*$", out, re.M)
        m_ret  = re.search(r"^\s*retention:\s*(true|false)\s*$", out, re.M | re.I)
        size_b = int(m_size.group(1)) if m_size else None
        retention = (m_ret.group(1).lower() == "true") if m_ret else None

        size_mb = round((size_b or 0) / (1024 * 1024), 1)
        passed = False
        if retention is True:
            passed = True
        elif size_b is not None and size_mb >= min_mb:
            passed = True

        return {
            "sfr": "FAU_SAR.1",
            "control_id": "AU-003",
            "title": "Audit log retention (Security log)",
            "passed": passed,
            "evidence": {
                "retention_enabled": retention,
                "max_size_mb": size_mb,
                "threshold_mb": min_mb
            },
            "severity": "High"
        }
    except Exception as e:
        return {
            "sfr": "FAU_SAR.1",
            "control_id": "AU-003",
            "title": "Audit log retention (Security log)",
            "passed": False,
            "evidence": {"error": str(e)},
            "severity": "High"
        }

# ---------- Control #5: FPT_STM.1 (Reliable time service) ----------
def chk_FPT_STM_1(max_age_hours: int = 24):
    """
    Ensure system time is reliable:
      - w32time service Running
      - StartType Automatic (or Automatic (Delayed))
      - NTP server configured (not Local CMOS Clock)
      - Last Successful Sync within max_age_hours
    """
    try:
        # 1) Service status + start type (PowerShell gives clean fields)
        ps = "Get-Service w32time | Select-Object -ExpandProperty Status; " \
             "(Get-WmiObject -Class Win32_Service -Filter \"Name='w32time'\").StartMode"
        out = run(["powershell","-NoProfile","-Command", ps])
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        status = lines[0] if lines else "Unknown"
        start_mode = (lines[1] if len(lines) > 1 else "Unknown")  # Auto | Manual | Disabled

        is_running = status.lower() == "running"
        is_auto = start_mode.lower().startswith("auto")  # Auto or Auto (Delayed Start)

        # 2) NTP configuration
        cfg = run(["w32tm","/query","/configuration"])
        m_ntp = re.search(r"^NtpServer:\s*(.+)$", cfg, re.M | re.I)
        ntp_server_raw = (m_ntp.group(1).strip() if m_ntp else "")
        has_ntp = bool(ntp_server_raw and ntp_server_raw.lower() != "not configured")

        # 3) Sync status (Source + last success time)
        st = run(["w32tm","/query","/status"])
        m_source = re.search(r"^Source:\s*(.+)$", st, re.M)
        source = (m_source.group(1).strip() if m_source else "Unknown")
        not_cmos = source.lower() != "local cmos clock"

        # "Last Successful Sync Time: 9/1/2025 1:23:45 PM"
        m_last = re.search(r"^Last Successful Sync Time:\s*(.+)$", st, re.M | re.I)
        last_ok = False
        last_when_iso = None
        if m_last:
            raw = m_last.group(1).strip()
            # Let Windows parse it via PowerShell to avoid locale headaches
            try:
                ps_parse = f"[datetime]::Parse('{raw}').ToUniversalTime().ToString('o')"
                iso = run(["powershell","-NoProfile","-Command", ps_parse]).strip()
                last_when_iso = iso
                # Compare to now
                from datetime import datetime, timezone
                last_dt = datetime.fromisoformat(iso.replace('Z','+00:00'))
                age_h = (datetime.now(timezone.utc) - last_dt).total_seconds()/3600.0
                last_ok = age_h <= max_age_hours
            except Exception:
                last_ok = False

        passed = is_running and is_auto and has_ntp and not_cmos and last_ok

        return {
            "sfr": "FPT_STM.1",
            "control_id": "PT-001",
            "title": "Reliable time service configured",
            "passed": passed,
            "evidence": {
                "service_status": status,
                "start_mode": start_mode,
                "ntp_server_raw": ntp_server_raw,
                "source": source,
                "last_successful_sync_utc": last_when_iso,
                "max_age_hours": max_age_hours
            },
            "severity": "High"
        }
    except Exception as e:
        return {
            "sfr": "FPT_STM.1",
            "control_id": "PT-001",
            "title": "Reliable time service configured",
            "passed": False,
            "evidence": {"error": str(e)},
            "severity": "High"
        }

# ---------- Control #6: FAU_STG.1 (Protect audit log files: Security.evtx) ----------
def chk_FAU_STG_1():
    """
    Only trusted identities may have write-like rights to:
      C:\Windows\System32\winevt\Logs\Security.evtx

    Write-like rights = F (Full), M (Modify), W (Write). The (I) token is just "inherited" and must be ignored.
    Allowed writers:
      - NT AUTHORITY\SYSTEM
      - BUILTIN\Administrators
      - LOCAL SERVICE
      - NT SERVICE\EventLog
    """
    import re

    # ---- safe defaults so except can never crash ----
    path = r"C:\Windows\System32\winevt\Logs\Security.evtx"
    allowed_write = {
        r"NT AUTHORITY\SYSTEM",
        r"BUILTIN\ADMINISTRATORS",
        r"LOCAL SERVICE",
        r"NT SERVICE\EVENTLOG",
    }
    WRITE_TOKENS = {"F", "M", "W"}  # treat these as write-like

    write_like = []     # [{principal, rights}]
    offenders  = []     # subset of write_like not in allow-list
    evidence   = {}
    passed     = False

    def norm(s: str) -> str:
        return (s or "").strip().strip('"').upper()

    def allowed_match(principal_norm: str) -> bool:
        """
        Be tolerant of prefixes like MACHINE\Administrators or extra spacing.
        We compare case-insensitively and allow the principal to END WITH the allowed token.
        """
        return any(principal_norm.endswith(norm(a)) for a in allowed_write)

    try:
        icacls_out = run(["icacls", path])
        evidence["path"] = path
        evidence["icacls"] = icacls_out

        for raw in icacls_out.splitlines():
            line = raw.strip()
            if not line or line.endswith(":"):
                continue
            # skip summary lines
            lo = line.lower()
            if lo.startswith("processed ") or lo.startswith("failed processing"):
                continue

            if ":" not in line:
                continue
            princ_raw, rest = line.split(":", 1)
            princ_norm = norm(princ_raw)

            # Collect (...) groups; drop the inheritance flag "I"; keep only write-like tokens
            tokens = re.findall(r"\(([^)]+)\)", rest)
            rights_no_I = [t for t in tokens if t and t.upper() != "I"]
            write_tokens = [t for t in rights_no_I if t.upper() in WRITE_TOKENS]

            if write_tokens:
                entry = {"principal": princ_raw.strip(), "rights": "(" + ")(".join(write_tokens) + ")"}
                write_like.append(entry)

                if not allowed_match(princ_norm):
                    offenders.append(entry)

        passed = (len(offenders) == 0)

        return {
            "sfr": "FAU_STG.1",
            "control_id": "AU-004",
            "title": "Protect audit log files (Security.evtx)",
            "passed": passed,
            "evidence": {
                **evidence,
                "write_like": write_like,                # write-capable entries (I removed)
                "offenders": offenders,                  # non-allowed writers
                "allowed_writers": sorted(list(allowed_write)),
            },
            "severity": "High",
        }

    except Exception as e:
        return {
            "sfr": "FAU_STG.1",
            "control_id": "AU-004",
            "title": "Protect audit log files (Security.evtx)",
            "passed": False,
            "evidence": {
                "error": str(e),
                **evidence,
                "write_like": write_like,
                "offenders": offenders,
                "allowed_writers": sorted(list(allowed_write)),
            },
            "severity": "High",
        }



# ---------- Control #7: FIA_SOS.1 (Password policy strength) ----------
def chk_FIA_SOS_1(min_len: int = 8, max_age_days: int = 365):
    """
    Ensure local password policy is strong:
      - Password complexity enabled
      - Minimum length >= min_len
      - Maximum age <= max_age_days
    Prefer 'secedit /export' -> secpol.cfg (UTF-16 LE), fall back to 'net accounts'.
    """
    try:
        # Try Local Security Policy export
        run(["secedit", "/export", "/cfg", "secpol.cfg"])
        text = open("secpol.cfg", encoding="utf-16-le", errors="ignore").read()

        def g(key, cast=int):
            m = re.search(rf"^{re.escape(key)}\s*=\s*([^\r\n]+)", text, re.M)
            return cast(m.group(1).strip()) if m else None

        complexity = g("PasswordComplexity", int)        # 0/1
        minlen     = g("MinimumPasswordLength", int)
        maxage     = g("MaximumPasswordAge", int)         # days

        passed = (
            (complexity == 1) and
            (minlen is not None and minlen >= min_len) and
            (maxage is not None and 0 < maxage <= max_age_days)
        )

        return {
            "sfr": "FIA_SOS.1",
            "control_id": "AC-002",
            "title": "Password policy strength",
            "passed": passed,
            "evidence": {
                "source": "secedit",
                "PasswordComplexity": complexity,
                "MinimumPasswordLength": minlen,
                "MaximumPasswordAge_days": maxage,
                "thresholds": {"min_len": min_len, "max_age_days": max_age_days}
            },
            "severity": "High"
        }
    except Exception:
        # Fallback to 'net accounts'
        try:
            out = run(["net", "accounts"])
            # Examples:
            #   Minimum password length (8)
            #   Password complexity requirement: Enabled
            #   Maximum password age (42 days)
            m_min = re.search(r"Minimum\s+password\s+length\s*\(?(\d+)\)?", out, re.I)
            m_age = re.search(r"Maximum\s+password\s+age\s*\(?(\d+)", out, re.I)  # first number = days
            m_cpx = re.search(r"(?:Password\s+complexity|complexity\s+requirement)\s*:\s*(Enabled|Disabled)", out, re.I)

            minlen = int(m_min.group(1)) if m_min else None
            maxage = int(m_age.group(1)) if m_age else None
            complexity = 1 if (m_cpx and m_cpx.group(1).lower() == "enabled") else 0 if m_cpx else None

            passed = (
                (complexity == 1) and
                (minlen is not None and minlen >= min_len) and
                (maxage is not None and 0 < maxage <= max_age_days)
            )

            return {
                "sfr": "FIA_SOS.1",
                "control_id": "AC-002",
                "title": "Password policy strength",
                "passed": passed,
                "evidence": {
                    "source": "net accounts",
                    "PasswordComplexityEnabled": (complexity == 1) if complexity is not None else None,
                    "MinimumPasswordLength": minlen,
                    "MaximumPasswordAge_days": maxage,
                    "thresholds": {"min_len": min_len, "max_age_days": max_age_days}
                },
                "severity": "High"
            }
        except Exception as e2:
            return {
                "sfr": "FIA_SOS.1",
                "control_id": "AC-002",
                "title": "Password policy strength",
                "passed": False,
                "evidence": {"error": str(e2)},
                "severity": "High"
            }

def chk_FAU_GEN_2():
    """Pass if logs contain essential fields: EventID, TimeCreated, TargetUserName."""
    try:
        xml = query_events_xml([4624, 4625], lookback_minutes=30)
        events = parse_events(xml)

        essentials = {"event_id", "time_created", "target_user"}
        # validate first few events
        ok = all(all(e.get(f) for f in essentials) for e in events[:5])

        # show concise evidence
        sample = []
        for e in events[:3]:
            sample.append({
                "event_id": e.get("event_id"),
                "time_created": e.get("time_created"),
                "target_user": e.get("target_user"),
                "ip": e.get("ip"),
                "snippet": e.get("message")
            })

        return {
            "sfr": "FAU_GEN.2",
            "control_id": "AU-005",
            "title": "Log content includes key fields",
            "passed": ok,
            "evidence": sample,
            "severity": "High"
        }
    except Exception as e:
        return {
            "sfr": "FAU_GEN.2",
            "control_id": "AU-005",
            "title": "Log content includes key fields",
            "passed": False,
            "evidence": {"error": str(e)},
            "severity": "High"
        }

# ---------- Control #9: FIA_UAU.1 (Built-in Administrator disabled) ----------
def chk_FIA_UAU_1():
    """
    Pass if the local built-in Administrator (RID 500) account is disabled.
    Uses PowerShell Get-LocalUser to find the SID ending in -500.
    """
    try:
        ps = r"Get-LocalUser | Where-Object {$_.SID -match '-500$'} | Select-Object Name,Enabled"
        out = run(["powershell","-NoProfile","-Command", ps]).strip()

        # Parse simple table output: lines like "Name Enabled"
        name = None
        enabled = None
        for line in out.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("name"):
                continue
            # split on whitespace; last token is Enabled
            parts = line.split()
            if len(parts) >= 2:
                enabled_str = parts[-1]
                name = " ".join(parts[:-1])
                enabled = (enabled_str.lower() == "true")

        passed = (enabled is False)  # must be disabled

        return {
            "sfr": "FIA_UAU.1",
            "control_id": "AC-003",
            "title": "Built-in Administrator disabled",
            "passed": passed,
            "evidence": {"account_name": name, "enabled": enabled},
            "severity": "High"
        }
    except Exception as e:
        return {
            "sfr": "FIA_UAU.1",
            "control_id": "AC-003",
            "title": "Built-in Administrator disabled",
            "passed": False,
            "evidence": {"error": str(e)},
            "severity": "High"
        }

# ---------- Control #10: FIA_SOS.2 (Password history & min age) ----------
def chk_FIA_SOS_2(min_history: int = 5, min_age_days: int = 1):
    """
    Ensure password history and minimum age are enforced:
      - PasswordHistorySize >= min_history
      - MinimumPasswordAge >= min_age_days
    Prefer 'secedit /export' -> secpol.cfg (UTF-16 LE), then fallback to 'net accounts'.
    """
    try:
        # Preferred: Local Security Policy export
        run(["secedit", "/export", "/cfg", "secpol.cfg"])
        text = open("secpol.cfg", encoding="utf-16-le", errors="ignore").read()

        def g(key, cast=int):
            m = re.search(rf"^{re.escape(key)}\s*=\s*([^\r\n]+)", text, re.M)
            return cast(m.group(1).strip()) if m else None

        hist = g("PasswordHistorySize", int)          # count
        minage = g("MinimumPasswordAge", int)         # days

        passed = (
            (hist is not None and hist >= min_history) and
            (minage is not None and minage >= min_age_days)
        )

        return {
            "sfr": "FIA_SOS.2",
            "control_id": "AC-004",
            "title": "Password history & minimum age",
            "passed": passed,
            "evidence": {
                "source": "secedit",
                "PasswordHistorySize": hist,
                "MinimumPasswordAge_days": minage,
                "thresholds": {"min_history": min_history, "min_age_days": min_age_days}
            },
            "severity": "High"
        }
    except Exception:
        # Fallback: 'net accounts'
        try:
            out = run(["net", "accounts"])
            # Examples seen in 'net accounts' output:
            #   Minimum password age (1 days)
            #   Password history length (24)
            m_hist = re.search(r"Password\s+history\s+length\s*\(?(\d+)\)?", out, re.I)
            m_age  = re.search(r"Minimum\s+password\s+age\s*\(?(\d+)", out, re.I)

            hist = int(m_hist.group(1)) if m_hist else None
            minage = int(m_age .group(1)) if m_age  else None

            passed = (
                (hist is not None and hist >= min_history) and
                (minage is not None and minage >= min_age_days)
            )

            return {
                "sfr": "FIA_SOS.2",
                "control_id": "AC-004",
                "title": "Password history & minimum age",
                "passed": passed,
                "evidence": {
                    "source": "net accounts",
                    "PasswordHistorySize": hist,
                    "MinimumPasswordAge_days": minage,
                    "thresholds": {"min_history": min_history, "min_age_days": min_age_days}
                },
                "severity": "High"
            }
        except Exception as e2:
            return {
                "sfr": "FIA_SOS.2",
                "control_id": "AC-004",
                "title": "Password history & minimum age",
                "passed": False,
                "evidence": {"error": str(e2)},
                "severity": "High"
            }



# ---------- Control #11: FIA_UAU.2 (Guest account disabled) ----------
def chk_FIA_UAU_2():
    """
    Pass if the local Guest account (RID 501) is disabled.
    Uses PowerShell Get-LocalUser to find SID ending in -501.
    """
    try:
        ps = r"Get-LocalUser | Where-Object {$_.SID -match '-501$'} | Select-Object Name,Enabled"
        out = run(["powershell","-NoProfile","-Command", ps]).strip()

        name, enabled = None, None
        for line in out.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("name"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                enabled_str = parts[-1]
                name = " ".join(parts[:-1])
                enabled = (enabled_str.lower() == "true")

        passed = (enabled is False)

        return {
            "sfr": "FIA_UAU.2",
            "control_id": "AC-005",
            "title": "Guest account disabled",
            "passed": passed,
            "evidence": {"account_name": name, "enabled": enabled},
            "severity": "High"
        }
    except Exception as e:
        return {
            "sfr": "FIA_UAU.2",
            "control_id": "AC-005",
            "title": "Guest account disabled",
            "passed": False,
            "evidence": {"error": str(e)},
            "severity": "High"
        }



# ---------- Control #12: FIA_AFL.2 (Lockout duration & reset counter) ----------
def chk_FIA_AFL_2(min_duration_min: int = 15, max_reset_min: int = 15):
    """
    Ensure account lockout duration and reset window meet policy:
      - LockoutDuration >= min_duration_min (minutes)
      - ResetLockoutCount <= max_reset_min (minutes)
    Prefer 'secedit /export' -> secpol.cfg; fallback to 'net accounts'.
    """
    try:
        # Preferred: Local Security Policy export
        run(["secedit", "/export", "/cfg", "secpol.cfg"])
        text = open("secpol.cfg", encoding="utf-16-le", errors="ignore").read()

        def grab(key):
            m = re.search(rf"^{re.escape(key)}\s*=\s*([^\r\n]+)", text, re.M)
            return int(m.group(1).strip()) if m else None

        duration = grab("LockoutDuration")        # minutes
        reset    = grab("ResetLockoutCount")      # minutes

        passed = (
            (duration is not None and duration >= min_duration_min) and
            (reset    is not None and reset    <= max_reset_min)
        )

        return {
            "sfr": "FIA_AFL.2",
            "control_id": "AU-006",
            "title": "Lockout duration & reset window",
            "passed": passed,
            "evidence": {
                "source": "secedit",
                "LockoutDuration_min": duration,
                "ResetLockoutCount_min": reset,
                "thresholds": {"min_duration_min": min_duration_min, "max_reset_min": max_reset_min}
            },
            "severity": "High"
        }
    except Exception:
        # Fallback: 'net accounts'
        try:
            out = run(["net", "accounts"])
            # Example lines:
            #   Lockout duration               (30 minutes)
            #   Reset account lockout counter after (15 minutes)
            m_dur   = re.search(r"Lockout\s+duration\s*\(?(\d+)", out, re.I)
            m_reset = re.search(r"Reset\s+account\s+lockout\s+counter\s+after\s*\(?(\d+)", out, re.I)

            duration = int(m_dur.group(1)) if m_dur else None
            reset    = int(m_reset.group(1)) if m_reset else None

            passed = (
                (duration is not None and duration >= min_duration_min) and
                (reset    is not None and reset    <= max_reset_min)
            )

            return {
                "sfr": "FIA_AFL.2",
                "control_id": "AU-006",
                "title": "Lockout duration & reset window",
                "passed": passed,
                "evidence": {
                    "source": "net accounts",
                    "LockoutDuration_min": duration,
                    "ResetLockoutCount_min": reset,
                    "thresholds": {"min_duration_min": min_duration_min, "max_reset_min": max_reset_min}
                },
                "severity": "High"
            }
        except Exception as e2:
            return {
                "sfr": "FIA_AFL.2",
                "control_id": "AU-006",
                "title": "Lockout duration & reset window",
                "passed": False,
                "evidence": {"error": str(e2)},
                "severity": "High"
            }


# ---------- Event query (XPath time filter) ----------
def query_events_xml(event_ids, lookback_minutes=5):
    """Query Security log for EventIDs within last lookback_minutes using XPath."""
    ms = int(lookback_minutes * 60 * 1000)
    id_clause = " or ".join([f"(EventID={eid})" for eid in event_ids])
    xpath = f"*[(System[{id_clause}] and System[TimeCreated[timediff(@SystemTime) <= {ms}]])]"
    return run(["wevtutil","qe","Security","/q:"+xpath,"/f:RenderedXml","/rd:true"])

import html
import re

def parse_events(xml):
    events = []

    def find(pattern, text, flags=re.I):
        m = re.search(pattern, text, flags)
        return m.group(1).strip() if m else ""

    for block in re.split(r"(?i)(?=<Event )", xml):
        if "<Event " not in block:
            continue

        # Core fields
        eid = find(r"<EventID>(\d+)</EventID>", block)
        ts  = find(r'TimeCreated\s+SystemTime="([^"]+)"', block)

        # Pull <RenderingInfo> and unescape the inner text
        m_msg = re.search(r"<RenderingInfo[^>]*>(.*?)</RenderingInfo>", block, re.I | re.S)
        msg_raw = m_msg.group(1) if m_msg else ""
        msg_text = re.sub(r"<[^>]+>", "", msg_raw)         # strip any tags inside RenderingInfo
        msg_text = html.unescape(msg_text)                 # turn &#13; etc. into real chars
        msg_text = re.sub(r"[\r\n]+", " ", msg_text).strip()

        # Structured fields (preferred)
        t_user = find(r'<Data Name="TargetUserName">([^<]*)</Data>', block)
        s_user = find(r'<Data Name="SubjectUserName">([^<]*)</Data>', block)
        ip     = find(r'<Data Name="IpAddress">([^<]*)</Data>', block)

        # Fallbacks from the human message if needed
        if not t_user:
            t_user = find(r"Account Name:\s*([^\s\r\n]+)", msg_text)
        if not ip:
            ip = "N/A"

        # Finalize
        events.append({
            "event_id": int(eid) if eid else None,
            "time_created": ts or None,
            "target_user": t_user or (s_user or "UNKNOWN"),
            "ip": ip,
            # keep message short for evidence (comment out if you don’t need it)
            "message": msg_text[:300] + ("…" if len(msg_text) > 300 else "")
        })

    return events


# ---------- Detection 1: 4625 failed-logon burst ----------
LOOKBACK_MIN = 5
BRUTE_4625_THRESHOLD = 5

def detect_bruteforce_4625(events, threshold=BRUTE_4625_THRESHOLD, window_min=LOOKBACK_MIN):
    counts, last_ip = defaultdict(int), {}
    for e in events:
        if e["event_id"] != 4625:
            continue
        acct = e.get("target_user", "UNKNOWN")
        counts[acct] += 1
        if e.get("ip") and e["ip"] != "N/A":
            last_ip[acct] = e["ip"]
    alerts = []
    for acct, n in counts.items():
        if n >= threshold:
            alerts.append({
                "rule_id":"BRUTE_4625","sfr_refs":["FIA_AFL.1","FAU_GEN.1","FAU_SAR.1"],
                "severity":"high","when": iso_now(),
                "summary": f"{n} failed logons for '{acct}' in last {window_min} min",
                "evidence":{"event_id":4625,"account":acct,"count":n,"window_min":window_min,
                           "last_ip": last_ip.get(acct,"N/A")}
            })
    return alerts

# ---------- Detection 2: 4728/4732 admin group add ----------
ADMIN_GROUPS = {"Administrators", "Domain Admins", "Enterprise Admins"}

def detect_admin_group_add(events):
    alerts = []
    for e in events:
        if e["event_id"] not in (4728, 4732):
            continue
        grp = re.search(r"Group(?:\s*Name)?:\s*([^\r\n]+)", e["message"], re.I)
        mem = re.search(r"Member(?:\s*Name)?:\s*([^\r\n]+)", e["message"], re.I)
        if not grp:
            grp = re.search(r'<Data Name="TargetUserName">([^<]*)</Data>', e["message"], re.I)
        if not mem:
            mem = re.search(r'<Data Name="MemberName">([^<]*)</Data>', e["message"], re.I)
        g = (grp.group(1).strip() if grp else "UNKNOWN")
        m = (mem.group(1).strip() if mem else "UNKNOWN")
        if g in ADMIN_GROUPS:
            alerts.append({
                "rule_id":"ADMIN_CHANGE_4728_4732",
                "sfr_refs":["FMT_SMR.1","FMT_MOF.1","FAU_GEN.1"],
                "severity":"high","when": iso_now(),
                "summary": f"User added to privileged group '{g}': {m}",
                "evidence":{"event_ids":[4728,4732],"group":g,"member":m}
            })
    return alerts

# ---------- main ----------
if __name__ == "__main__":
    if sys.platform != "win32":
        print("Run this on Windows.", file=sys.stderr); sys.exit(1)

    # Compliance — 4 controls now
    comp = [chk_FIA_AFL_1(), chk_FMT_SMR_1(), chk_FAU_GEN_1(), chk_FAU_SAR_1(),  chk_FPT_STM_1(), chk_FAU_STG_1(), chk_FIA_SOS_1(),  chk_FAU_GEN_2(), chk_FIA_UAU_1(), chk_FIA_SOS_2(), chk_FIA_UAU_2(), chk_FIA_AFL_2()]

    # Detections (already wrapped)
    alerts = []
    try:
        xml = query_events_xml([4625, 4728, 4732], lookback_minutes=LOOKBACK_MIN)
        events = parse_events(xml)
        alerts += detect_bruteforce_4625(events)
        alerts += detect_admin_group_add(events)
    except Exception as e:
        alerts.append({
            "rule_id": "RUNTIME_NOTE",
            "severity": "low",
            "summary": "Skipped eventlog detections (insufficient permission to read Security log).",
            "evidence": {"error": str(e)}
        })

    print(json.dumps({"compliance": comp, "alerts": alerts}, indent=2))

