# backend/api.py
from flask import Blueprint, jsonify, request, current_app, make_response
from sqlalchemy import func, desc
import os, json, datetime as dt

from .models import db, AuditEvent
from .ingest_samples import project_root, ingest_audit

# --------- Blueprints ---------
sample_bp = Blueprint("sample_api", __name__, url_prefix="/api/sample")
api_bp    = Blueprint("api",        __name__, url_prefix="/api")

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

# --------- Auto-sync samples/audit.json -> DB ---------
def _ensure_samples_synced():
    """If samples/audit.json changed since last time, (re)ingest into DB."""
    audit_path = _audit_sample_path()
    mtime = _file_mtime(audit_path)
    state = _load_state()
    last = state.get("audit_json_mtime", 0.0)
    if mtime <= last:
        return
    count = ingest_audit(current_app, audit_path)
    state["audit_json_mtime"] = mtime
    _save_state(state)
    current_app.logger.info(f"Samples synced -> DB: {count} rows from {audit_path}")

# --------- Unique rows query (dedupe at API level) ---------
def _unique_rows_query(*, category=None, outcome=None, date_from=None, date_to=None, q=None):
    """
    Build a query that returns unique audit events by (time, category, control, outcome, account, description),
    even if the table contains duplicates with different IDs.
    """
    base = db.session.query(AuditEvent)

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

    sub = base.subquery()  # select * from filtered rows
    uq = db.session.query(
        func.min(sub.c.id).label("id"),
        sub.c.time.label("time"),
        sub.c.category.label("category"),
        sub.c.control.label("control"),
        sub.c.outcome.label("outcome"),
        sub.c.account.label("account"),
        sub.c.description.label("description"),
    ).group_by(
        sub.c.time, sub.c.category, sub.c.control,
        sub.c.outcome, sub.c.account, sub.c.description
    )
    return uq  # query of unique rows

def _unique_count():
    """Total unique rows across the whole table."""
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

    # Default monthly from UNIQUE DB rows (percent per month)
    months = []
    # Use the min/max from the raw table to pick a month range (ok for POC)
    min_dt = db.session.query(func.min(AuditEvent.time)).scalar()
    max_dt = db.session.query(func.max(AuditEvent.time)).scalar()
    if min_dt and max_dt:
        # unique events subquery for re-use in month filters
        uq_all = _unique_rows_query().subquery()
        cursor = dt.datetime(max_dt.year, max_dt.month, 1)
        for _ in range(6):
            mstart = cursor
            mend = dt.datetime(
                cursor.year + (1 if cursor.month == 12 else 0),
                1 if cursor.month == 12 else cursor.month + 1,
                1
            )

            mtotal = db.session.query(func.count()).select_from(uq_all)\
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

# --------- Shared responders ---------
def _resp_json(obj, *, source_header="db-sample", dashboard_source=None):
    resp = make_response(jsonify(obj))
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

    # Make it a subquery so we can access columns via .c
    uq = _unique_rows_query(
        category=category,
        outcome=outcome,
        date_from=date_from,
        date_to=date_to,
        q=q if q else None
    ).subquery()

    # Now select from the subquery and order/limit
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


# --------- /api/sample/* ---------
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

# --------- /api/* alias ---------
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
