from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class AuditEvent(db.Model):
    __tablename__ = "audit_events"
    id          = db.Column(db.Integer, primary_key=True)
    time        = db.Column(db.DateTime, nullable=False, index=True)
    category    = db.Column(db.String(64), index=True)
    control     = db.Column(db.String(128))
    outcome     = db.Column(db.String(32), index=True)   # e.g., "Failed", "Info"
    account     = db.Column(db.String(128))
    description = db.Column(db.Text)
    source      = db.Column(db.String(16), index=True, default="sample")  # e.g., "sample", "live"
    host        = db.Column(db.String(128))

    def to_dict(self):
        return {
            "id": self.id,
            "time": (self.time.isoformat() + "Z") if isinstance(self.time, datetime) else None,
            "category": self.category,
            "control": self.control,
            "outcome": self.outcome,
            "account": self.account,
            "description": self.description,
            "source": self.source,
            "host": self.host,
        }

class SecurityEvent(db.Model):
    __tablename__ = "security_events"
    id        = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(db.Integer, index=True)                   # EventRecordID (for de-dupe)
    time      = db.Column(db.DateTime, nullable=False, index=True)  # UTC
    event_id  = db.Column(db.Integer, index=True)
    channel   = db.Column(db.String(64), default="Security")
    provider  = db.Column(db.String(128))
    level     = db.Column(db.String(32))
    account   = db.Column(db.String(128))   # normalized target/subject
    target    = db.Column(db.String(128))   # extra slot for 47xx "member"
    ip        = db.Column(db.String(64))
    message   = db.Column(db.Text)          # short, rendered snippet
    raw_xml   = db.Column(db.Text)          # optional drilldown
    source    = db.Column(db.String(16), index=True, default="sample")  # sample|live
    host      = db.Column(db.String(128))

    __table_args__ = (
        db.UniqueConstraint("source", "host", "channel", "record_id", name="ux_events_unique"),
    )

    def to_dict(self, include_raw: bool=False):
        d = {
            "id": self.id,
            "time": (self.time.isoformat() + "Z") if isinstance(self.time, datetime) else None,
            "event_id": self.event_id,
            "channel": self.channel,
            "provider": self.provider,
            "level": self.level,
            "account": self.account,
            "target": self.target,
            "ip": self.ip,
            "message": self.message,
            "source": self.source,
            "host": self.host,
            "record_id": self.record_id,
        }
        if include_raw:
            d["raw_xml"] = self.raw_xml
        return d

class Detection(db.Model):
    __tablename__ = "detections"
    id       = db.Column(db.Integer, primary_key=True)
    when     = db.Column(db.DateTime, nullable=False, index=True)   # UTC
    rule_id  = db.Column(db.String(64), index=True)
    severity = db.Column(db.String(16), index=True)                 # low|medium|high|critical
    summary  = db.Column(db.Text)
    evidence = db.Column(db.Text)                                   # JSON string
    account  = db.Column(db.String(128))
    ip       = db.Column(db.String(64))
    source   = db.Column(db.String(16), index=True, default="sample")
    host     = db.Column(db.String(128))
    status   = db.Column(db.String(16), index=True, default="new")  # new|ack|muted

    def to_dict(self):
        return {
            "id": self.id,
            "when": (self.when.isoformat() + "Z") if isinstance(self.when, datetime) else None,
            "rule_id": self.rule_id,
            "severity": self.severity,
            "summary": self.summary,
            "evidence": self.evidence,
            "account": self.account,
            "ip": self.ip,
            "source": self.source,
            "host": self.host,
            "status": self.status,
        }

class EventBookmark(db.Model):
    __tablename__ = "event_bookmarks"
    id            = db.Column(db.Integer, primary_key=True)
    channel       = db.Column(db.String(64), index=True, default="Security")
    host          = db.Column(db.String(128), index=True)
    source        = db.Column(db.String(16), index=True, default="live")
    last_record_id= db.Column(db.Integer, default=0)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("channel", "host", "source", name="ux_bookmark_unique"),
    )
