# backend/ingest_samples.py
import os, json
from datetime import datetime
from flask import Flask
from .models import db, AuditEvent

def project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

def instance_path():
    return os.path.join(os.path.dirname(__file__), "instance")

def create_app_for_ingest():
    app = Flask(__name__, instance_path=instance_path(), instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    db_path = os.path.join(app.instance_path, "occt.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
    return app

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_time(s: str):
    if not s:
        return datetime.utcnow()
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1]
    return datetime.fromisoformat(s)

def ingest_audit(app, audit_json_path):
    """(Re)load samples/audit.json into the app's DB."""
    data = load_json(audit_json_path)
    assert isinstance(data, list), "samples/audit.json must be a JSON array"
    inserted = 0
    with app.app_context():
        db.session.query(AuditEvent).delete()
        db.session.commit()
        for row in data:
            evt = AuditEvent(
                time=parse_time(row.get("time")),
                category=row.get("category") or "Audit",
                control=row.get("control") or "",
                outcome=row.get("outcome") or "Info",
                account=row.get("account") or "",
                description=(row.get("description") or "")[:4096],
            )
            db.session.add(evt)
            inserted += 1
        db.session.commit()
    return inserted

# Optional CLI: python -m backend.ingest_samples
if __name__ == "__main__":
    app = create_app_for_ingest()
    n = ingest_audit(app, os.path.join(project_root(), "samples", "audit.json"))
    print(f"[OK] Ingested {n} audit events into {os.path.join(app.instance_path, 'occt.db')}")
