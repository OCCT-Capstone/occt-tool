# backend/live_poller.py
import os, sys, time, subprocess, re, html
import threading
import datetime as dt
from collections import defaultdict
from sqlalchemy.exc import IntegrityError
from .models import db, SecurityEvent, Detection, EventBookmark
from .notify import publish_detection  # <-- NEW

# ---- instrumentation for clarity ----
_POLL_STARTED = False
def _print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass

# ------------ Helpers ------------
def _is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def _log(app, msg):
    _print(msg)

def iso_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def to_dt_utc(s):
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None

def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{(p.stderr or p.stdout).strip()}")
    return p.stdout

def query_events_xml(event_ids, lookback_minutes=5):
    """Query Security log for specific EventIDs within last lookback_minutes using XPath."""
    ms = int(lookback_minutes * 60 * 1000)
    id_clause = " or ".join([f"(EventID={eid})" for eid in event_ids])
    xpath = f"*[(System[{id_clause}] and System[TimeCreated[timediff(@SystemTime) <= {ms}]])]"
    return run(["wevtutil", "qe", "Security", "/q:" + xpath, "/f:RenderedXml", "/rd:true"])

def _find(pattern, text, flags=re.I):
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else ""

def _data_map(block: str) -> dict:
    return {
        m.group(1): (m.group(2) or "").strip()
        for m in re.finditer(r'<Data\s+Name="([^"]+)">([^<]*)</Data>', block, re.I)
    }

def _clean_rendered_text(block: str) -> str:
    m_msg = re.search(r"<RenderingInfo[^>]*>(.*?)</RenderingInfo>", block, re.I | re.S)
    raw = m_msg.group(1) if m_msg else ""
    txt = re.sub(r"<[^>]+>", "", raw)
    txt = html.unescape(txt)
    txt = re.sub(r"[\r\n\t]+", " ", txt)
    txt = re.sub(r"\s{2,}", " ", txt).strip()
    return txt

def _clean_text(s: str) -> str:
    if not s: return ""
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def _message_text(block: str) -> str:
    m = re.search(r"<Message>(.*?)</Message>", block, re.I | re.S)
    raw = m.group(1) if m else ""
    raw = re.sub(r"<[^>]+>", "", raw)
    return _clean_text(raw)

def _cap(pat: str, text: str):
    m = re.search(pat, text, re.I | re.S)
    return m.group(1).strip() if m else None

def _norm_account(x: str | None) -> str | None:
    x = (x or "").strip()
    return None if x in {"", "-", "N/A"} else x

def _norm_ip(x: str | None) -> str:
    x = (x or "").strip()
    return "N/A" if x in {"", "-"} else x

def parse_events(xml: str):
    events = []
    for block in re.split(r"(?i)(?=<Event )", xml or ""):
        if "<Event " not in block:
            continue

        provider = _find(r'<Provider[^>]*Name="([^"]+)"', block) or "Microsoft-Windows-Security-Auditing"
        channel  = _find(r"<Channel>([^<]*)</Channel>", block) or "Security"
        level    = _find(r"<Level>([^<]*)</Level>", block) or None
        record   = _find(r"<EventRecordID>(\d+)</EventRecordID>", block)
        eid_str  = _find(r"<EventID>(\d+)</EventID>", block)
        ts       = _find(r'TimeCreated[^>]*SystemTime="([^"]+)"', block)
        eid      = int(eid_str) if eid_str else None

        msg_full = _message_text(block)
        data     = _data_map(block)

        # ---- Account extraction ----
        account = None
        if eid == 4624:
            account = _cap(r"New Logon:.*?Account Name:\s*(.*?)\s*(?=Account Domain:)", msg_full)
        elif eid == 4625:
            account = _cap(r"Account For Which Logon Failed:.*?Account Name:\s*(.*?)\s*(?=Account Domain:)", msg_full)
        elif eid in (4728, 4732):
            account = _cap(r"Member:.*?Account Name:\s*(.*?)\s*(?=Group:|Group Name:|Group Domain:|Additional Information:|$)", msg_full)

        if not account:
            account = (data.get("TargetUserName") or data.get("TargetUser") or
                       data.get("MemberName") or data.get("SubjectUserName") or None)
        account = _norm_account(_clean_text(account) if account else None)

        # ---- IP extraction ----
        ip = _cap(r"Source Network Address:\s*([^\s]+)", msg_full) or None
        ip = _norm_ip(ip)

        events.append({
            "record_id": int(record) if record else None,
            "time": to_dt_utc(ts),
            "event_id": eid,
            "channel": channel,
            "provider": provider,
            "level": level,
            "account": account or None,
            "target":  account or None,
            "ip": ip,
            "message": msg_full,
        })
    return events

# ------------ DB IO ------------
def get_bookmark(channel="Security", host="", source="live"):
    bm = EventBookmark.query.filter_by(channel=channel, host=host, source=source).first()
    if not bm:
        bm = EventBookmark(channel=channel, host=host, source=source, last_record_id=0)
        db.session.add(bm); db.session.commit()
    return bm

def insert_events(events, host, source="live"):
    inserted = 0
    for e in events:
        try:
            se = SecurityEvent(
                record_id = e.get("record_id"),
                time      = e.get("time") or dt.datetime.now(dt.timezone.utc),
                event_id  = e.get("event_id"),
                channel   = e.get("channel") or "Security",
                provider  = e.get("provider") or "",
                level     = e.get("level"),
                account   = e.get("account") or None,
                target    = e.get("target") or None,
                ip        = e.get("ip") or None,
                message   = e.get("message") or "",
                raw_xml   = None,
                source    = source,
                host      = host or None,
            )
            db.session.add(se)
            db.session.flush()
            inserted += 1
        except IntegrityError:
            db.session.rollback()
    return inserted

def json_dumps(x):
    try:
        import json
        return json.dumps(x, ensure_ascii=False)
    except Exception:
        return "{}"

def upsert_detections(alerts, window_min, source="live", host=""):
    """
    Insert detections if not seen in the sliding window; return (inserted_count, newly_inserted_alerts).
    Newly inserted alerts are in the same shape as the incoming 'alerts'.
    """
    inserted = 0
    now = dt.datetime.now(dt.timezone.utc)
    window = dt.timedelta(minutes=max(window_min, 5))
    new_alerts = []

    for a in alerts:
        when_dt = to_dt_utc(a.get("when")) or now
        exists = Detection.query.filter(
            Detection.source == source,
            Detection.rule_id == a.get("rule_id"),
            Detection.summary == a.get("summary"),
            Detection.when >= (now - window),
        ).first()
        if exists:
            continue

        det = Detection(
            when     = when_dt,
            rule_id  = a.get("rule_id"),
            severity = a.get("severity") or "medium",
            summary  = a.get("summary") or "",
            evidence = json_dumps(a.get("evidence") or {}),
            account  = a.get("account") or None,
            ip       = a.get("ip") or None,
            source   = source,
            host     = host or None,
            status   = "new",
        )
        db.session.add(det)
        inserted += 1
        new_alerts.append(a)

    return inserted, new_alerts

# ------------ Detections ------------
BRUTE_4625_THRESHOLD_DEFAULT = 5

def detect_bruteforce_4625(events, threshold, window_min):
    counts, last_ip = defaultdict(int), {}
    for e in events:
        if e.get("event_id") != 4625:
            continue
        acct = (e.get("account") or "").strip()
        if not acct:
            acct = f"IP:{e.get('ip') or 'N/A'}"
        counts[acct] += 1
        ip = e.get("ip")
        if ip and ip != "N/A":
            last_ip[acct] = ip

    alerts = []
    for acct, n in counts.items():
        if n >= threshold:
            alerts.append({
                "rule_id": "BRUTE_4625",
                "severity": "high",
                "when": iso_now(),
                "summary": f"{n} failed logons for '{acct}' in last {window_min} min",
                "evidence": {
                    "event_id": 4625, "account": acct, "count": n,
                    "window_min": window_min, "last_ip": last_ip.get(acct, "N/A"),
                    "threshold": threshold
                },
                "account": acct if not acct.startswith("IP:") else None,
                "ip": last_ip.get(acct, "N/A"),
            })
    return alerts

ADMIN_GROUPS = {"Administrators", "Domain Admins", "Enterprise Admins"}

def detect_admin_group_add(events, window_min):
    alerts = []
    for e in events:
        if e.get("event_id") not in (4728, 4732):
            continue
        msg = e.get("message") or ""

        grp = _cap(r"Group Name:\s*(.*?)\s*(?=Group Domain:|Additional Information:|$)", msg)
        mem = _cap(r"Member:.*?Account Name:\s*(.*?)\s*(?=Group:|Group Name:|Group Domain:|Additional Information:|$)", msg)
        g = (grp or "").strip() or "UNKNOWN"
        m = (mem or (e.get("target") or "UNKNOWN")).strip()

        if g in ADMIN_GROUPS:
            alerts.append({
                "rule_id":"ADMIN_CHANGE_4728_4732",
                "severity":"high",
                "when": iso_now(),
                "summary": f"User added to privileged group '{g}': {m}",
                "evidence":{"event_ids":[4728,4732],"group":g,"member":m},
                "account": m if m and m != "-" else None,
                "ip": "N/A",
            })
    return alerts

# ------------ Poll cycle ------------
def _poll_once(app, event_ids, lookback_min, brute_thr, host, source):
    with app.app_context():
        try:
            bm = get_bookmark(channel="Security", host=host, source=source)
            xml = query_events_xml(event_ids, lookback_minutes=lookback_min)
            evs = parse_events(xml)

            if bm.last_record_id:
                evs = [e for e in evs if (e.get("record_id") or 0) > (bm.last_record_id or 0)]

            ins_events = insert_events(evs, host=host, source=source)

            alerts = []
            if evs:
                a1 = detect_bruteforce_4625(evs, threshold=brute_thr, window_min=lookback_min)
                a2 = detect_admin_group_add(evs, window_min=lookback_min)

                # Hard guard: never let an under-threshold BRUTE slip in
                safe_a1 = []
                for a in a1:
                    ev = a.get("evidence") or {}
                    if ev.get("count", 0) >= brute_thr:
                        safe_a1.append(a)
                alerts = safe_a1 + a2

            ins_alerts, new_alerts = upsert_detections(alerts, window_min=lookback_min, source=source, host=host)

            # publish only newly-inserted alerts to SSE
            published = 0
            for a in new_alerts:
                publish_detection({
                    "rule_id": a.get("rule_id"),
                    "summary": a.get("summary"),
                    "severity": a.get("severity") or "medium",
                    "account": a.get("account"),
                    "host": host,
                    "ip": a.get("ip"),
                    "when": a.get("when"),
                })
                published += 1

            max_rec = max([e.get("record_id") or 0 for e in evs] or [bm.last_record_id or 0])
            if max_rec > (bm.last_record_id or 0):
                bm.last_record_id = max_rec
                bm.updated_at = dt.datetime.utcnow()
                db.session.add(bm)

            db.session.commit()
            _log(app, f"[detections] +{ins_events} events, +{ins_alerts} alerts (published {published}), bookmark={bm.last_record_id}")
        except Exception as e:
            db.session.rollback()
            _log(app, f"[detections] error: {e}")
        finally:
            db.session.remove()

def _loop(app, event_ids, interval_sec, lookback_min, brute_thr, host, source):
    _log(app, f"[detections] live poller started (ids={tuple(event_ids)}, every {interval_sec}s, lookback={lookback_min}m)")
    while True:
        _poll_once(app, event_ids, lookback_min, brute_thr, host, source)
        time.sleep(max(5, interval_sec))

# ------------ Entry ------------
def start_live_poller_if_enabled(app):
    global _POLL_STARTED
    _print("[detections] start_live_poller_if_enabled called")

    # Avoid double-start under Flask/Werkzeug reloader
    if getattr(app, "debug", False) and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        _print("[detections] dev reloader primary process; skipping poller start")
        return

    if _POLL_STARTED:
        _print("[detections] already started; skipping")
        return

    if sys.platform != "win32":
        _print("[detections] live poller disabled (not Windows)")
        return

    if not app.config.get("DETECTIONS_LIVE", True):
        _print("[detections] live poller disabled by config (DETECTIONS_LIVE=False)")
        return

    def _is_admin():
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    if not _is_admin():
        _print("[detections] live poller disabled: process not elevated. Run VS Code as Administrator or use scripts/run-admin.ps1")
        return

    event_ids = tuple(int(x) for x in app.config.get("DETECTIONS_EVENT_IDS", [4625, 4728, 4732, 4624]))
    lookback  = int(app.config.get("DETECTIONS_LOOKBACK_MIN", 5))
    interval  = int(app.config.get("DETECTIONS_INTERVAL", 15))
    brute_thr = int(app.config.get("BRUTE_4625_THRESHOLD", BRUTE_4625_THRESHOLD_DEFAULT))
    host      = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or ""
    source    = "live"

    t = threading.Thread(
        target=_loop,
        args=(app, event_ids, interval, lookback, brute_thr, host, source),
        daemon=True,
        name="occt-detections-poller",
    )
    t.start()
    _POLL_STARTED = True
    _print(f"[detections] live poller started (ids={event_ids}, every {interval}s, lookback={lookback}m, threshold={brute_thr})")
