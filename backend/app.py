# backend/app.py
from flask import (
    Flask, render_template, request, jsonify, redirect, url_for, session
)
from functools import wraps
from .db_util import ensure_c1_columns
from .live_facts import attach_live_facts, attach_live_compliance
from .live_facts import attach_live_rules_api
import os

from .models import db  # shared SQLAlchemy instance

app = Flask(
    __name__,
    template_folder="../frontend",
    static_folder="../frontend",
    static_url_path="",
    instance_relative_config=True,
)

# Sessions
app.config["SECRET_KEY"] = os.getenv("OCCT_SECRET_KEY", "dev-secret-change-me")
app.config["SESSION_COOKIE_NAME"] = "occt_session"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Ensure instance/
os.makedirs(app.instance_path, exist_ok=True)

# SQLite
db_path = os.path.join(app.instance_path, "occt.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
with app.app_context():
    db.create_all()
    ensure_c1_columns()

# Blueprints
from .api import api_bp, sample_bp, live_bp   # <-- add live_bp
attach_live_facts(live_bp, app)               # add live facts endpoint
attach_live_compliance(live_bp, app)          # add live compliance stats endpoint
attach_live_rules_api(live_bp, app)           # add live rules management endpoints
app.register_blueprint(sample_bp)             # /api/sample/*
app.register_blueprint(api_bp)                # /api/*
app.register_blueprint(live_bp)               # /api/live/*

# Auth (unchanged)
ADMIN_USER = "admin"
ADMIN_PASS = "Password123!"

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login_page"))
        return view(*args, **kwargs)
    return wrapped

@app.get("/login")
def login_page():
    if session.get("user"):
        return redirect(url_for("index"))
    return render_template("login.html")

@app.post("/auth/login")
def auth_login():
    data = request.get_json(silent=True) or {}
    u = (data.get("username") or "").strip()
    p = data.get("password") or ""
    if u == ADMIN_USER and p == ADMIN_PASS:
        session["user"] = u
        return jsonify(ok=True)
    return jsonify(ok=False, error="invalid"), 401

@app.post("/auth/logout")
def auth_logout():
    session.clear()
    return jsonify(ok=True)

# Protected pages
@app.get("/")
@login_required
def index():
    return render_template("index.html")

@app.get("/audit")
@login_required
def audit_page():
    return render_template("audit.html")

@app.get("/remediation")
@login_required
def remediation_page():
    return render_template("remediation.html")

@app.get("/settings")
@login_required
def settings_page():
    return render_template("settings.html")

# Health
@app.get("/healthz")
def healthz():
    return {"ok": True}

if __name__ == "__main__":
    app.run(debug=True, port=5000)
