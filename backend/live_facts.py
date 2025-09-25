# backend/live_facts.py
import os, datetime as dt
from flask import request, jsonify
from .models import db, AuditEvent
from .live_rules import evaluate_facts_document, load_rules

# Auto-detect rules file: prefer YAML, fallback to JSON
_RULES_DIR = os.path.join(os.path.dirname(__file__), "rules")
_RULES_YAML = os.path.join(_RULES_DIR, "controls.yml")
_RULES_JSON = os.path.join(_RULES_DIR, "controls.json")
if os.path.exists(_RULES_YAML):
    RULES_PATH = _RULES_YAML
elif os.path.exists(_RULES_JSON):
    RULES_PATH = _RULES_JSON
else:
    RULES_PATH = _RULES_YAML

_PATH = os.path.join(os.path.dirname(__file__), "rules", "controls.yml")

def _parse_iso(s):
    if not s:
        return None
    s = s.strip().replace("Z", "")
    try:
        return dt.datetime.fromisoformat(s) if "T" in s else dt.datetime.fromisoformat(s + "T00:00:00")
    except Exception:
        return None

def _insert_events(rows):
    inserted = 0
    for r in rows:
        evt = AuditEvent(
            time=_parse_iso(r.get("time")) or dt.datetime.utcnow(),
            category=(r.get("category") or "")[:64],
            control=(r.get("control") or "")[:128],
            outcome=(r.get("outcome") or "Info")[:32],
            account=(r.get("account") or "")[:128],
            description=(r.get("description") or "")[:4096],
        )
        # Set additive fields if present on the model (Sprint 1 added them)
        try: evt.source = "live"
        except Exception: pass
        try: evt.host = (r.get("host") or "")[:128]
        except Exception: pass

        db.session.add(evt); inserted += 1
    db.session.commit()
    return inserted

def attach_live_facts(live_bp, app):
    """Attach /api/live/facts to your existing LIVE blueprint. Call this before registering the blueprint."""
    @live_bp.post("/facts")
    def post_facts():
        try:
            payload = request.get_json(force=True, silent=False) or {}
        except Exception as ex:
            return jsonify({"error": "invalid_json", "detail": str(ex)}), 400

        rows = evaluate_facts_document(payload, RULES_PATH)
        n = _insert_events(rows)
        return jsonify({"ok": True, "inserted": n})
    
def attach_live_compliance(live_bp, app):
    @live_bp.get("/stats/compliance")
    def live_compliance():
        # Basic compliance = Passed / (Passed + Failed). Ignores Info/other.
        from sqlalchemy import text
        where = "1=1"
        # Force source='live' if the column exists
        try:
            cols = [r[1] for r in db.session.execute(text("PRAGMA table_info(audit_events)")).all()]
            if "source" in cols:
                where += " AND source = 'live'"
        except Exception:
            pass
        sql = text(f"""
            SELECT
              SUM(CASE WHEN outcome='Passed' THEN 1 ELSE 0 END) AS passed,
              SUM(CASE WHEN outcome='Failed' THEN 1 ELSE 0 END) AS failed
            FROM audit_events
            WHERE {where}
        """)
        row = db.session.execute(sql).first()
        passed = int(row[0] or 0)
        failed = int(row[1] or 0)
        total = passed + failed
        pct = (passed / total * 100.0) if total else 0.0
        return jsonify({
            "passed": passed,
            "failed": failed,
            "total": total,
            "compliance_pct": round(pct, 1)
        })

def attach_live_rules_api(live_bp, app):
    @live_bp.get("/rules")
    def live_rules_api():
        try:
            rules = load_rules(RULES_PATH)
        except Exception as ex:
            return jsonify({"error": "rules_load_failed", "detail": str(ex)}), 500
        # Return only what the UI needs
        return jsonify([
            {
                "id": r.get("id"),
                "title": r.get("title"),
                "category": r.get("category"),
                "remediation": r.get("remediation", "")
            }
            for r in rules
        ])

