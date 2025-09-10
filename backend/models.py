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

    def to_dict(self):
        return {
            "id": self.id,
            "time": self.time.isoformat() + "Z",
            "category": self.category,
            "control": self.control,
            "outcome": self.outcome,
            "account": self.account,
            "description": self.description,
        }
