# backend/api.py
from flask import Blueprint, jsonify, request, current_app
import os, json, datetime as dt

# /api  (live)
api_bp = Blueprint("api", __name__, url_prefix="/api")
# /api/sample (samples)
sample_bp = Blueprint("sample_api", __name__, url_prefix="/api/sample")

def _project_root():
    # backend/ -> project root
    return os.path.abspath(os.path.join(current_app.root_path, os.pardir))

def _read_sample(name: str):
    """Read JSON from samples/<name>.json"""
    p = os.path.join(_project_root(), "samples", f"{name}.json")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

# ---------- SAMPLE ENDPOINTS ----------

@sample_bp.get("/dashboard")
def sample_dashboard():
    data = _read_sample("dashboard")
    return jsonify(data)

@sample_bp.get("/audit")
def sample_audit():
    rows = _read_sample("audit")
    # Optional light filtering so UI controls work even with samples
    q = (request.args.get("q") or "").lower().strip()
    cat = request.args.get("category") or ""
    outcome = request.args.get("outcome") or ""
    date_from = request.args.get("from")
    date_to   = request.args.get("to")

    def in_range(tiso: str) -> bool:
        try:
            t = dt.datetime.fromisoformat(tiso.replace("Z","+00:00"))
        except Exception:
            return True
        if date_from:
            if t < dt.datetime.fromisoformat(date_from + "T00:00:00+00:00"):
                return False
        if date_to:
            if t > dt.datetime.fromisoformat(date_to + "T23:59:59+00:00"):
                return False
        return True

    def match(row):
        if cat and row.get("category") != cat:
            return False
        if outcome and row.get("outcome") != outcome:
            return False
        if not in_range(row.get("time","")):
            return False
        if q:
            hay = " ".join([
                row.get("description",""), row.get("control",""),
                row.get("account",""), row.get("category","")
            ]).lower()
            if q not in hay:
                return False
        return True

    filtered = [r for r in rows if match(r)]
    return jsonify(filtered)

# ---------- LIVE ENDPOINTS (stubbed) ----------
# Later, replace these to pull from SQLite / collectors.

@api_bp.get("/dashboard")
def live_dashboard():
    # TODO: replace with real DB/collector query
    return sample_dashboard()   # reuse sample for now

@api_bp.get("/audit")
def live_audit():
    # TODO: replace with real DB/collector query
    return sample_audit()       # reuse sample for now
