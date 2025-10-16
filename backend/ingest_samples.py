# backend/ingest_samples.py
import os
import json
from datetime import datetime, timezone
from flask import Flask
from sqlalchemy.sql import or_
from .models import db, AuditEvent

# --- paths ----------------------------------------------------

def project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

def instance_path():
    return os.path.join(os.path.dirname(__file__), "instance")

# --- app factory for CLI usage --------------------------------

def create_app_for_ingest():
    app = Flask(__name__, instance_path=instance_path(), instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    db_path = os.path.join(app.instance_path, "occt.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path.replace('\\', '/')}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
    return app

# --- helpers --------------------------------------------------

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_time(s: str):
    """Parse ISO 8601 with optional trailing Z; fall back to now (UTC)."""
    if not s:
        return datetime.now(timezone.utc)
    s = s.strip()
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.now(timezone.utc)

# --- main ingest ----------------------------------------------

def ingest_audit(app, audit_json_path):
    """
    (Re)load samples/audit.json into the DB WITHOUT touching live rows.
    Strategy:
      1) Read JSON.
      2) Delete only prior sample rows that match these controls/accounts and are not source='live'.
      3) Insert fresh rows with source='sample' (and host if present).
    """
    data = load_json(audit_json_path)
    assert isinstance(data, list), "samples/audit.json must be a JSON array"

    # Build quick filters so we ONLY remove prior sample rows for these controls/accounts
    controls = { (r.get("control") or "").strip() for r in data if r.get("control") }
    accounts = { (r.get("account") or "").strip() for r in data if r.get("account") }

    inserted = 0
    with app.app_context():
        # 1) Delete ONLY previous sample rows for these controls/accounts.
        #    Important: we EXPLICITLY avoid deleting source='live'.
        if controls or accounts:
            q = db.session.query(AuditEvent)

            if controls:
                q = q.filter(AuditEvent.control.in_(list(controls)))
            if accounts:
                q = q.filter(AuditEvent.account.in_(list(accounts)))

            # Keep live. Delete rows where source != 'live' (including NULL/empty).
            q = q.filter(or_(AuditEvent.source.is_(None), AuditEvent.source != "live"))

            q.delete(synchronize_session=False)
            db.session.commit()

        # 2) Insert the fresh sample rows (tagged as source='sample')
        for row in data:
            evt = AuditEvent(
                time        = parse_time(row.get("time")),
                category    = (row.get("category") or "Audit").strip(),
                control     = (row.get("control") or "").strip(),
                outcome     = (row.get("outcome") or "Info").strip(),
                account     = (row.get("account") or "").strip(),
                description = (row.get("description") or "")[:4096],
            )
            # Tag as sample; set host if the column exists in model
            try:
                evt.source = "sample"
            except Exception:
                pass
            try:
                host_val = (row.get("host") or "").strip()
                if hasattr(evt, "host"):
                    evt.host = host_val[:128]
            except Exception:
                pass

            db.session.add(evt)
            inserted += 1

        db.session.commit()

    return inserted

# Optional CLI: python -m backend.ingest_samples
if __name__ == "__main__":
    app = create_app_for_ingest()
    samples_path = os.path.join(project_root(), "samples", "audit.json")
    n = ingest_audit(app, samples_path)
    print(f"[OK] Ingested {n} sample events into {os.path.join(app.instance_path, 'occt.db')}")
