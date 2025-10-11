# backend/api.py
from flask import Blueprint, jsonify, request, current_app, make_response, render_template
from sqlalchemy import func, desc
import os, json, datetime as dt
import threading

from .models import db, AuditEvent
from .ingest_samples import project_root, ingest_audit

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
        # Re-load state inside the lock
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

# --------- Unique rows query (API-level dedupe) ---------
def _unique_rows_query(*, category=None, outcome=None, date_from=None, date_to=None, q=None):
    # Decide dataset by blueprint (sample_api vs live_api)
    mode = "live" if (getattr(request, "blueprint", "") == "live_api") else "sample"

    base = db.session.query(AuditEvent)

    # Filter by source only if the column exists on the model (Option A adds it)
    try:
        from sqlalchemy import inspect
        cols = [c.key for c in inspect(AuditEvent).c]
        if "source" in cols:
            base = base.filter(AuditEvent.source == mode)
    except Exception:
        # If models.py doesn't have 'source' yet, skip filtering (Option B path)
        pass

    # (keep your existing filters below)
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
    # use sample report behavior
    return sample_report()

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

# --------- LAST SCAN endpoints (sample & live) ---------
@sample_bp.get("/last-scan")
def sample_last_scan():
    _ensure_samples_synced()
    # Latest timestamp (for display only)
    t = db.session.query(func.max(AuditEvent.time))\
        .filter(AuditEvent.source == "sample").scalar()

    if not t:
        return _resp_json({
            "has_data": False,
            "completed_at": None,
            "event_count": 0,
            "failed_count": 0,
            "host_count": 0
        }, source_header="db-sample")

    # For SAMPLE, show totals across the whole sample dataset (not a time window)
    total_events = db.session.query(func.count(AuditEvent.id))\
        .filter(AuditEvent.source == "sample").scalar() or 0

    failed_events = db.session.query(func.count(AuditEvent.id))\
        .filter(
            AuditEvent.source == "sample",
            func.lower(AuditEvent.outcome) == "failed"
        ).scalar() or 0

    # Infer hosts when 'host' is empty: use 'account' values that look like machine names.
    # Ignore known non-host accounts.
    rows = db.session.query(AuditEvent.host, AuditEvent.account)\
        .filter(AuditEvent.source == "sample").all()

    NON_HOST_ACCOUNTS = {"domain", "ad-policy", "ad policy", "adpolicy", "adminGroup".lower(), "all users"}
    host_set = set()
    for h, a in rows:
        h = (h or "").strip()
        a = (a or "").strip()
        if h:
            host_set.add(h)
            continue
        # Heuristic: treat account as host if it's not a known non-host label and has no spaces
        # (e.g., SRV-WS001, SRV-DB01, SRV-FS01)
        if a and " " not in a and a.lower() not in NON_HOST_ACCOUNTS:
            host_set.add(a)

    return _resp_json({
        "has_data": True,
        "completed_at": t.isoformat() + "Z",
        "event_count": int(total_events),
        "failed_count": int(failed_events),
        "host_count": int(len(host_set))
    }, source_header="db-sample")



@live_bp.get("/last-scan")
def live_last_scan():
    t = db.session.query(func.max(AuditEvent.time)).filter(AuditEvent.source == "live").scalar()
    if not t:
        return _resp_json({"has_data": False, "completed_at": None, "event_count": 0, "failed_count": 0, "host_count": 0}, source_header="db-live")
    start = t.replace(second=0, microsecond=0)
    end   = start + dt.timedelta(minutes=1)
    rows = db.session.query(AuditEvent).filter(
        AuditEvent.source == "live",
        AuditEvent.time >= start,
        AuditEvent.time < end
    ).all()
    return _resp_json({
        "has_data": True,
        "completed_at": t.isoformat() + "Z",
        "event_count": len(rows),
        "failed_count": sum(1 for r in rows if (r.outcome or "").lower() == "failed"),
        "host_count": len({(r.host or "").strip() for r in rows if (r.host or "").strip()}),
    }, source_header="db-live")
