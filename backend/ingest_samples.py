# backend/ingest_samples.py
import os
import json
from datetime import datetime, timezone
from flask import Flask
from sqlalchemy.sql import or_
from .models import db, AuditEvent, SecurityEvent, Detection

def project_root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

def instance_path():
    return os.path.join(os.path.dirname(__file__), "instance")

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

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def parse_time(s: str):
    if not s:
        return datetime.now(timezone.utc)
    s = s.strip()
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.now(timezone.utc)

def ingest_audit(app, audit_json_path):
    data = load_json(audit_json_path)
    assert isinstance(data, list), "samples/audit.json must be a JSON array"
    inserted = 0
    with app.app_context():
        db.session.query(AuditEvent).filter(
            or_(AuditEvent.source == "sample", AuditEvent.source.is_(None))
        ).delete(synchronize_session=False)
        db.session.commit()

        for row in data:
            evt = AuditEvent(
                time        = parse_time(row.get("time")),
                category    = (row.get("category") or "Audit").strip(),
                control     = (row.get("control") or "").strip(),
                outcome     = (row.get("outcome") or "Info").strip(),
                account     = (row.get("account") or "").strip(),
                description = (row.get("description") or "")[:4096],
                source      = "sample",
                host        = (row.get("host") or "").strip()[:128] or None
            )
            db.session.add(evt); inserted += 1
        db.session.commit()
    return inserted

def ingest_security_events(app, events_json_path):
    if not os.path.exists(events_json_path): return 0
    data = load_json(events_json_path)
    assert isinstance(data, list), "samples/events.json must be a JSON array"
    inserted = 0
    with app.app_context():
        db.session.query(SecurityEvent).filter(SecurityEvent.source == "sample").delete(synchronize_session=False)
        db.session.commit()
        for r in data:
            se = SecurityEvent(
                record_id = r.get("record_id"),
                time      = parse_time(r.get("time")),
                event_id  = r.get("event_id"),
                channel   = (r.get("channel") or "Security").strip(),
                provider  = (r.get("provider") or "").strip(),
                level     = (r.get("level") or "").strip() or None,
                account   = (r.get("account") or "").strip() or None,
                target    = (r.get("target") or "").strip() or None,
                ip        = (r.get("ip") or "").strip() or None,
                message   = (r.get("message") or "")[:800],
                raw_xml   = r.get("raw_xml"),
                source    = "sample",
                host      = (r.get("host") or "SAMPLE-HOST").strip()[:128]
            )
            db.session.add(se); inserted += 1
        db.session.commit()
    return inserted

def ingest_detections(app, alerts_json_path):
    if not os.path.exists(alerts_json_path): return 0
    data = load_json(alerts_json_path)
    assert isinstance(data, list), "samples/alerts.json must be a JSON array"
    inserted = 0
    with app.app_context():
        db.session.query(Detection).filter(Detection.source == "sample").delete(synchronize_session=False)
        db.session.commit()
        for a in data:
            det = Detection(
                when     = parse_time(a.get("when") or a.get("time")),
                rule_id  = (a.get("rule_id") or "").strip(),
                severity = (a.get("severity") or "medium").strip(),
                summary  = (a.get("summary") or "").strip(),
                evidence = json.dumps(a.get("evidence") or {}, ensure_ascii=False),
                account  = (a.get("account") or "").strip() or None,
                ip       = (a.get("ip") or "").strip() or None,
                source   = "sample",
                host     = (a.get("host") or "SAMPLE-HOST").strip()[:128],
                status   = (a.get("status") or "new").strip()
            )
            db.session.add(det); inserted += 1
        db.session.commit()
    return inserted

if __name__ == "__main__":
    app = create_app_for_ingest()
    root = project_root()
    audit_path  = os.path.join(root, "samples", "audit.json")
    events_path = os.path.join(root, "samples", "events.json")
    alerts_path = os.path.join(root, "samples", "alerts.json")
    n1 = ingest_audit(app, audit_path)
    n2 = ingest_security_events(app, events_path)
    n3 = ingest_detections(app, alerts_path)
    print(f"[OK] Ingested {n1} audit, {n2} events, {n3} detections into {os.path.join(app.instance_path, 'occt.db')}")
