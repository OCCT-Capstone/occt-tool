# backend/api.py
from flask import Blueprint, jsonify, request, current_app, make_response, render_template, Response
from sqlalchemy import func, desc
import os, json, time, datetime as dt, yaml
import threading

from .models import db, AuditEvent, Detection
from .ingest_samples import project_root, ingest_audit
import backend.notify as _bus  # <— canonical import for the single SSE bus

# --------- Blueprints ---------
sample_bp = Blueprint("sample_api", __name__, url_prefix="/api/sample")  # DB-backed SAMPLE mode (auto-syncs from file)
api_bp    = Blueprint("api",        __name__, url_prefix="/api")         # alias your UI uses (same as sample)
live_bp   = Blueprint("live_api",   __name__, url_prefix="/api/live")    # DB-backed LIVE mode (no auto-sync)

_SAMPLES_SYNC_LOCK = threading.Lock()

# --------- Helpers: paths & state ---------
def _samples_dir():
    return os.path.join(project_root(), "samples")

def _audit_sample_path():
    return os.path.join(_samples_dir(), "audit.json")

def _dashboard_sample_path():
    return os.path.join(_samples_dir(), "dashboard.json")

def _state_path():
    return os.path.join(current_app.instance_path, "samples_state.json")

def _file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except FileNotFoundError:
        return 0.0

def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _load_state() -> dict:
    p = _state_path()
    if not os.path.exists(p):
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_state(state: dict):
    os.makedirs(current_app.instance_path, exist_ok=True)
    with open(_state_path(), "w", encoding="utf-8") as f:
        json.dump(state, f)

# --------- SAMPLE: auto-sync samples/audit.json -> DB ---------
def _ensure_samples_synced():
    """If samples/audit.json changed since last time, (re)ingest into DB.
       Protected by a lock to avoid double ingestion on concurrent requests."""
    audit_path = _audit_sample_path()
    mtime = _file_mtime(audit_path)
    state = _load_state()
    last = state.get("audit_json_mtime", 0.0)
    if mtime <= last:
        return

    # --- Lock + re-check to prevent races ---
    with _SAMPLES_SYNC_LOCK:
        state = _load_state()
        last = state.get("audit_json_mtime", 0.0)
        if mtime <= last:
            return
        count = ingest_audit(current_app, audit_path)
        state["audit_json_mtime"] = _file_mtime(audit_path)
        _save_state(state)
        current_app.logger.info(f"Samples synced -> DB: {count} rows from {audit_path}")

def _force_reingest_samples():
    """Always (re)ingest samples/audit.json into DB, ignoring mtime."""
    audit_path = _audit_sample_path()
    count = ingest_audit(current_app, audit_path)
    state = _load_state()
    state["audit_json_mtime"] = _file_mtime(audit_path)
    _save_state(state)
    return count

# --------- SQLA helpers ---------
def _has_column(model, colname: str) -> bool:
    try:
        from sqlalchemy import inspect
        return colname in [c.key for c in inspect(model).c]
    except Exception:
        return False

# --------- Unique rows query (API-level dedupe) ---------
def _unique_rows_query(*, category=None, outcome=None, date_from=None, date_to=None, q=None):
    # Decide dataset by blueprint (sample_api vs live_api vs api(alias->sample))
    mode = "live" if (request.blueprint == "live_api") else "sample"

    base = db.session.query(AuditEvent)

    # Filter by source only if column exists
    if _has_column(AuditEvent, "source"):
        base = base.filter(AuditEvent.source == mode)

    # Filters
    if category:
        base = base.filter(AuditEvent.category == category)
    if outcome:
        base = base.filter(AuditEvent.outcome == outcome)
    if date_from:
        base = base.filter(AuditEvent.time >= dt.datetime.fromisoformat(date_from + "T00:00:00"))
    if date_to:
        base = base.filter(AuditEvent.time <= dt.datetime.fromisoformat(date_to + "T23:59:59"))
    if q:
        like = f"%{q.strip().lower()}%"
        base = base.filter(
            (func.lower(AuditEvent.description).like(like)) |
            (func.lower(AuditEvent.control).like(like)) |
            (func.lower(AuditEvent.account).like(like))
        )

    # Dedupe by (time, category, control, outcome, account, description)
    sub = base.subquery()
    uq = db.session.query(
        func.min(sub.c.id).label("id"),
        sub.c.time, sub.c.category, sub.c.control, sub.c.outcome, sub.c.account, sub.c.description
    ).group_by(
        sub.c.time, sub.c.category, sub.c.control, sub.c.outcome, sub.c.account, sub.c.description
    )
    return uq

def _unique_count():
    uq_sub = _unique_rows_query().subquery()
    return db.session.query(func.count()).select_from(uq_sub).scalar() or 0

def _unique_failed_count():
    uq_sub = _unique_rows_query().subquery()
    return db.session.query(func.count()).select_from(uq_sub).filter(uq_sub.c.outcome == "Failed").scalar() or 0

# --------- Dashboard builder (summary from unique rows; monthly DB fallback + optional override) ---------
def _build_dashboard_json_with_optional_override():
    total_unique  = _unique_count()
    failed_unique = _unique_failed_count()
    passed_unique = max(total_unique - failed_unique, 0)

    compliant_percent     = round((passed_unique / total_unique) * 100, 2) if total_unique else 0.0
    non_compliant_percent = round(100.0 - compliant_percent, 2)

    # Default monthly from UNIQUE DB rows
    months = []
    min_dt = db.session.query(func.min(AuditEvent.time)).scalar()
    max_dt = db.session.query(func.max(AuditEvent.time)).scalar()
    if min_dt and max_dt:
        uq_all = _unique_rows_query().subquery()
        cursor = dt.datetime(max_dt.year, max_dt.month, 1)
        for _ in range(6):
            mstart = cursor
            mend = dt.datetime(
                cursor.year + (1 if cursor.month == 12 else 0),
                1 if cursor.month == 12 else cursor.month + 1,
                1
            )
            mtotal  = db.session.query(func.count()).select_from(uq_all)\
                        .filter(uq_all.c.time >= mstart, uq_all.c.time < mend).scalar() or 0
            mfailed = db.session.query(func.count()).select_from(uq_all)\
                        .filter(uq_all.c.time >= mstart, uq_all.c.time < mend, uq_all.c.outcome == "Failed").scalar() or 0
            mpassed = max(mtotal - mfailed, 0)

            if mtotal > 0:
                comp_pct = round((mpassed / mtotal) * 100, 2)
                nonc_pct = round(100.0 - comp_pct, 2)
            else:
                comp_pct = nonc_pct = 0.0

            months.append({
                "month": mstart.strftime("%Y-%m"),
                "compliant": comp_pct,
                "noncompliant": nonc_pct
            })

            cursor = dt.datetime(
                cursor.year - (1 if cursor.month == 1 else 0),
                12 if cursor.month == 1 else cursor.month - 1,
                1
            )
        months.reverse()

    payload = {
        "summary": {
            "compliant_percent": compliant_percent,
            "non_compliant_percent": non_compliant_percent,
            "passed_count": passed_unique,
            "failed_count": failed_unique,
            "total_checks": total_unique
        },
        "monthly": months
    }

    # If samples/dashboard.json exists, override monthly (and optional summary)
    dash_path = _dashboard_sample_path()
    try:
        if os.path.exists(dash_path):
            dj = _read_json(dash_path)
            if isinstance(dj, dict):
                if isinstance(dj.get("monthly"), list) and dj["monthly"]:
                    payload["monthly"] = dj["monthly"]
                    payload["_note_monthly"] = "monthly-from-dashboard-json"
                if isinstance(dj.get("summary"), dict):
                    s = dj["summary"]
                    if "compliant_percent" in s:
                        payload["summary"]["compliant_percent"] = s["compliant_percent"]
                        payload["_note_summary"] = "summary-from-dashboard-json"
                    if "non_compliant_percent" in s:
                        payload["summary"]["non_compliant_percent"] = s["non_compliant_percent"]
                        payload["_note_summary"] = "summary-from-dashboard-json"
    except Exception as ex:
        current_app.logger.warning(f"dashboard.json read error: {ex}")

    return payload

# --------- Remediation overview (unique failed only) ---------
def _build_remediation_overview():
    uq = _unique_rows_query().subquery()
    # counts by category (Failed)
    by_cat = db.session.query(
        uq.c.category, func.count().label("n")
    ).filter(uq.c.outcome == "Failed").group_by(uq.c.category).order_by(desc("n")).all()

    # top controls (Failed)
    by_ctrl = db.session.query(
        uq.c.control, func.count().label("n")
    ).filter(uq.c.outcome == "Failed").group_by(uq.c.control).order_by(desc("n")).limit(10).all()

    # recent failed events (deduped)
    recent = db.session.query(
        uq.c.time, uq.c.category, uq.c.control, uq.c.account, uq.c.description
    ).filter(uq.c.outcome == "Failed").order_by(desc(uq.c.time)).limit(10).all()

    # distinct accounts impacted (Failed)
    accounts = db.session.query(func.count(func.distinct(uq.c.account))).filter(
        uq.c.outcome == "Failed", uq.c.account.isnot(None), uq.c.account != ""
    ).scalar() or 0

    return {
        "by_category": [{"category": c or "(Uncategorized)", "failed": int(n)} for c, n in by_cat],
        "top_controls": [{"control": c or "(N/A)", "failed": int(n)} for c, n in by_ctrl],
        "recent_failed": [{
            "time": (t.isoformat() + "Z") if t else None,
            "category": cat, "control": ctrl, "account": acct, "description": descp
        } for (t, cat, ctrl, acct, descp) in recent],
        "accounts_impacted": int(accounts)
    }

# --------- Shared responders ---------
def _resp_json(obj, *, source_header="db-sample", dashboard_source=None, status=200):
    resp = make_response(jsonify(obj), status)
    resp.headers["X-OCCT-Source"] = source_header
    if dashboard_source:
        resp.headers["X-OCCT-Dashboard-Source"] = dashboard_source
    return resp

# --------- Core responder for audit list (UNIQUE rows only) ---------
def _build_audit_list_from_unique():
    q        = (request.args.get("q") or "").strip()
    category = request.args.get("category")
    outcome  = request.args.get("outcome")
    date_from= request.args.get("from")
    date_to  = request.args.get("to")

    uq = _unique_rows_query(
        category=category,
        outcome=outcome,
        date_from=date_from,
        date_to=date_to,
        q=q if q else None
    ).subquery()

    rows = db.session.query(
        uq.c.id, uq.c.time, uq.c.category, uq.c.control,
        uq.c.outcome, uq.c.account, uq.c.description
    ).order_by(desc(uq.c.time)).limit(500).all()

    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "time": r.time.isoformat() + "Z" if r.time else None,
            "category": r.category,
            "control": r.control,
            "outcome": r.outcome,
            "account": r.account,
            "description": r.description,
        })
    return out

# ===================== WEIGHTED COMPLIANCE =====================

def _candidate_controls_paths():
    here = os.path.dirname(__file__)
    roots = [
        os.path.join(here, "rules", "controls.yml"),
        os.path.join(here, "controls.yml"),
        os.path.join(project_root(), "backend", "rules", "controls.yml"),
        os.path.join(project_root(), "rules", "controls.yml"),
        os.path.join(project_root(), "config", "controls.yml"),
        os.path.join(project_root(), "controls.yml"),
    ]
    # First existing path wins
    return [p for p in roots if os.path.exists(p)]

def _rules_severity_index():
    """
    Return {<id or title lower>: 'low'|'medium'|'high'|'critical'} from controls.yml.
    Works with list or dict YAML layouts. Falls back to 'low' if unknown.
    """
    index = {}
    # Try importing live_rules (optional)
    try:
        from .live_rules import load_rules
        for p in _candidate_controls_paths():
            try:
                rules = load_rules(p) or []
                for r in rules:
                    sev = (r.get("severity") or r.get("risk") or "low").lower()
                    key_id = (r.get("id") or "").strip().lower()
                    key_title = (r.get("title") or r.get("control") or "").strip().lower()
                    if key_id:
                        index[key_id] = sev
                    if key_title:
                        index[key_title] = sev
                if index:
                    return index
            except Exception:
                pass
    except Exception:
        pass

    # Fallback: direct YAML read
    for p in _candidate_controls_paths():
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                for k, v in data.items():
                    if isinstance(v, dict):
                        sev = (v.get("severity") or v.get("risk") or "low").lower()
                        index[(k or "").strip().lower()] = sev
                        title = (v.get("title") or v.get("control") or "").strip().lower()
                        if title:
                            index[title] = sev
            elif isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        sev = (item.get("severity") or item.get("risk") or "low").lower()
                        key_id = (item.get("id") or "").strip().lower()
                        key_title = (item.get("title") or item.get("control") or "").strip().lower()
                        if key_id:
                            index[key_id] = sev
                        if key_title:
                            index[key_title] = sev
            if index:
                return index
        except Exception:
            continue
    return index  # may be empty

def _compute_weighted_compliance():
    """
    Risk-weighted compliance:
      - Each PASS contributes 1 unit.
      - Each FAIL contributes severity-weight units (low=1, med=2, high=3, critical=4).
    Score = 100 * P / (P + weighted_fail_units)
    """
    weights = {"low": 1, "medium": 2, "high": 3, "critical": 4}

    # Build severity index from controls.yml (id/title -> severity), fallback 'low'
    sev_index = _rules_severity_index()

    uq = _unique_rows_query().subquery()
    rows = db.session.query(uq.c.control, uq.c.outcome).all()

    pass_units = 0                      # 1 per pass
    fail_units = {"low": 0, "medium": 0, "high": 0, "critical": 0}  # weighted by severity

    for control, outcome in rows:
        key = (control or "").strip().lower()
        sev = sev_index.get(key, "low")
        w = weights.get(sev, 1)

        if (outcome or "").lower() == "failed":
            fail_units[sev] = fail_units.get(sev, 0) + w  # severity-weighted
        else:
            pass_units += 1                               # unweighted pass

    denom = pass_units + sum(fail_units.values())
    score = round((pass_units / denom) * 100) if denom else 0

    return {
        "score": score,
        "points": {
            # Keep names the JS expects:
            "total": denom,
            "pass": pass_units,                    # unweighted passes
            "fail_low": fail_units["low"],
            "fail_medium": fail_units["medium"],
            "fail_high": fail_units["high"],
            "fail_critical": fail_units["critical"],
        }
    }


# --------- SAMPLE endpoints (/api/sample/*) ---------
@sample_bp.get("/dashboard")
def sample_dashboard():
    _ensure_samples_synced()
    payload = _build_dashboard_json_with_optional_override()
    dash_src = "file-dashboard" if payload.get("_note_monthly") else "db"
    return _resp_json(payload, source_header="db-sample", dashboard_source=dash_src)

@sample_bp.get("/audit")
def sample_audit():
    _ensure_samples_synced()
    rows = _build_audit_list_from_unique()
    return _resp_json(rows, source_header="db-sample")

@sample_bp.post("/rescan")
def sample_rescan():
    n = _force_reingest_samples()
    total_unique  = _unique_count()
    failed_unique = _unique_failed_count()
    return _resp_json({
        "ok": True, "mode": "sample", "ingested": n,
        "total_unique": total_unique, "failed_unique": failed_unique
    }, source_header="db-sample")

@sample_bp.get("/report")
def sample_report():
    _ensure_samples_synced()
    dash = _build_dashboard_json_with_optional_override()
    rem  = _build_remediation_overview()
    html = render_template(
        "report.html",
        dashboard=dash,
        remediation=rem,
        generated_at=dt.datetime.utcnow(),
        mode="sample"
    )
    resp = make_response(html, 200)
    if request.args.get("download") == "1":
        fname = f"occt-report-{dt.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.html"
        resp.headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp

@sample_bp.get("/last-scan")
def sample_last_scan():
    _ensure_samples_synced()
    # Latest timestamp (for display only)
    q = db.session.query(func.max(AuditEvent.time))
    if _has_column(AuditEvent, "source"):
        q = q.filter(AuditEvent.source == "sample")
    t = q.scalar()

    if not t:
        return _resp_json({
            "has_data": False,
            "completed_at": None,
            "event_count": 0,
            "failed_count": 0,
            "host_count": 0
        }, source_header="db-sample")

    # Totals across sample dataset
    q_total = db.session.query(func.count(AuditEvent.id))
    q_failed = db.session.query(func.count(AuditEvent.id)).filter(func.lower(AuditEvent.outcome) == "failed")
    q_rows = db.session.query(AuditEvent.host, AuditEvent.account)

    if _has_column(AuditEvent, "source"):
        q_total  = q_total.filter(AuditEvent.source == "sample")
        q_failed = q_failed.filter(AuditEvent.source == "sample")
        q_rows   = q_rows.filter(AuditEvent.source == "sample")

    total_events  = q_total.scalar() or 0
    failed_events = q_failed.scalar() or 0

    rows = q_rows.all()
    NON_HOST_ACCOUNTS = {"domain", "ad-policy", "ad policy", "adpolicy", "admingroup".lower(), "all users"}
    host_set = set()
    for h, a in rows:
        h = (h or "").strip()
        a = (a or "").strip()
        if h:
            host_set.add(h)
            continue
        if a and " " not in a and a.lower() not in NON_HOST_ACCOUNTS:
            host_set.add(a)

    return _resp_json({
        "has_data": True,
        "completed_at": t.isoformat() + "Z",
        "event_count": int(total_events),
        "failed_count": int(failed_events),
        "host_count": int(len(host_set))
    }, source_header="db-sample")

# ---- Weighted compliance (sample) ----
@sample_bp.get("/weighted-compliance")
def sample_weighted_compliance():
    _ensure_samples_synced()
    payload = _compute_weighted_compliance()
    return _resp_json(payload, source_header="db-sample")

# --------- /api/* alias (same as sample so UI keeps working) ---------
@api_bp.get("/dashboard")
def alias_dashboard():
    _ensure_samples_synced()
    payload = _build_dashboard_json_with_optional_override()
    dash_src = "file-dashboard" if payload.get("_note_monthly") else "db"
    return _resp_json(payload, source_header="db-sample", dashboard_source=dash_src)

@api_bp.get("/audit")
def alias_audit():
    _ensure_samples_synced()
    rows = _build_audit_list_from_unique()
    return _resp_json(rows, source_header="db-sample")

@api_bp.post("/rescan")
def alias_rescan():
    return sample_rescan()

@api_bp.get("/report")
def alias_report():
    return sample_report()

# ---- Weighted compliance (alias) ----
@api_bp.get("/weighted-compliance")
def alias_weighted_compliance():
    _ensure_samples_synced()
    payload = _compute_weighted_compliance()
    return _resp_json(payload, source_header="db-sample")

# --------- LIVE endpoints (/api/live/*) ---------
@live_bp.get("/dashboard")
def live_dashboard():
    payload = _build_dashboard_json_with_optional_override()
    dash_src = "file-dashboard" if payload.get("_note_monthly") else "db"
    return _resp_json(payload, source_header="db-live", dashboard_source=dash_src)

@live_bp.get("/audit")
def live_audit():
    rows = _build_audit_list_from_unique()
    return _resp_json(rows, source_header="db-live")

@live_bp.get("/report")
def live_report():
    dash = _build_dashboard_json_with_optional_override()
    rem  = _build_remediation_overview()
    html = render_template(
        "report.html",
        dashboard=dash,
        remediation=rem,
        generated_at=dt.datetime.utcnow(),
        mode="live"
    )
    resp = make_response(html, 200)
    if request.args.get("download") == "1":
        fname = f"occt-report-{dt.datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.html"
        resp.headers["Content-Disposition"] = f'attachment; filename="{fname}"'
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    return resp

@live_bp.get("/last-scan")
def live_last_scan():
    # Most recent minute bucket for live
    q = db.session.query(func.max(AuditEvent.time))
    if _has_column(AuditEvent, "source"):
        q = q.filter(AuditEvent.source == "live")
    t = q.scalar()
    if not t:
        return _resp_json({"has_data": False, "completed_at": None, "event_count": 0, "failed_count": 0, "host_count": 0}, source_header="db-live")

    start = t.replace(second=0, microsecond=0)
    end   = start + dt.timedelta(minutes=1)

    rows_q = db.session.query(AuditEvent).filter(AuditEvent.time >= start, AuditEvent.time < end)
    if _has_column(AuditEvent, "source"):
        rows_q = rows_q.filter(AuditEvent.source == "live")
    rows = rows_q.all()

    return _resp_json({
        "has_data": True,
        "completed_at": t.isoformat() + "Z",
        "event_count": len(rows),
        "failed_count": sum(1 for r in rows if (r.outcome or "").lower() == "failed"),
        "host_count": len({(r.host or "").strip() for r in rows if (r.host or "").strip()}),
    }, source_header="db-live")

# ---- Weighted compliance (live) ----
@live_bp.get("/weighted-compliance")
def live_weighted_compliance():
    payload = _compute_weighted_compliance()
    return _resp_json(payload, source_header="db-live")

# --------- REAL-TIME SSE stream (LIVE) ---------
@live_bp.get("/stream")
def live_stream():
    """Server-Sent Events: stream detections to the UI in real time (no replay)."""
    resp = Response(_bus.sse_stream(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache, no-transform"
    resp.headers["Connection"] = "keep-alive"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp

# --------- (Optional) test endpoint to emit a demo detection ---------
@live_bp.post("/notify/test")
def live_notify_test():
    now = dt.datetime.utcnow().isoformat() + "Z"
    sample = {
        "rule_id": "TEST_RULE",
        "summary": "Demo detection event",
        "severity": "low",
        "account": "demo",
        "host": "localhost",
        "ip": "127.0.0.1",
        "when": now,
    }
    n = _bus.publish_detection(sample)
    return _resp_json({"ok": True, "when": now, "id": None, "published_to_clients": n}, source_header="db-live")

# --------- debug (optional) ---------
@live_bp.get("/debug/notify-state")
def live_notify_state():
    return _resp_json(_bus._debug_state(), source_header="db-live")

@live_bp.post("/debug/notify-clear")
def live_notify_clear():
    return _resp_json(_bus._debug_clear(), source_header="db-live")
