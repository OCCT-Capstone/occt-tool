# backend/app.py
from flask import (
    Flask, render_template, request, jsonify, redirect, url_for, session
)
from functools import wraps
from sqlalchemy import func
from .db_util import ensure_c1_columns, ensure_unique_index  # NOTE: no ensure_event_tables here
from .live_facts import attach_live_facts, attach_live_compliance, attach_live_rules_api
from .live_runner import attach_live_runner_api
from .detections_api import attach_detections_api
from .models import db, AuditEvent
from .live_poller import start_live_poller_if_enabled
import os

# ---------------- defaults + bootstrap of instance/settings.py ----------------

DEFAULT_SETTINGS = """# Auto-created by OCCT on first run.
# Toggle live detections poller (requires Administrator on Windows)
DETECTIONS_LIVE = True
DETECTIONS_EVENT_IDS = [4625, 4728, 4732, 4624]
DETECTIONS_LOOKBACK_MIN = 5     # minutes
DETECTIONS_INTERVAL = 15        # seconds
BRUTE_4625_THRESHOLD = 5
DETECTIONS_DEDUPE_SEC = 0       # seconds; 0 = no de-dupe (alerts fire immediately)
"""

def ensure_instance_settings_file(app):
    """Create instance/settings.py with defaults if it does not exist."""
    path = os.path.join(app.instance_path, "settings.py")
    if not os.path.exists(path):
        try:
            os.makedirs(app.instance_path, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_SETTINGS)
            print(f"[bootstrap] wrote default {path}")
        except Exception as e:
            print(f"[bootstrap] could not write {path}: {e}")

def apply_default_config(app):
    """Set in-code defaults; allow optional env overrides to keep flexibility."""
    app.config.from_mapping(
        DETECTIONS_LIVE=True,
        DETECTIONS_EVENT_IDS=[4625, 4728, 4732, 4624],
        DETECTIONS_LOOKBACK_MIN=5,
        DETECTIONS_INTERVAL=15,
        BRUTE_4625_THRESHOLD=5,
        DETECTIONS_DEDUPE_SEC=0,
    )
    # Optional: allow env overrides if provided
    def env_int(name, default):
        v = os.getenv(name)
        try:
            return int(v) if v is not None else default
        except Exception:
            return default
    def env_csv_int(name, default_list):
        v = os.getenv(name)
        if not v: return default_list
        out = []
        for x in v.split(","):
            x = x.strip()
            if x.isdigit():
                out.append(int(x))
        return out or default_list

    if "OCCT_DETECTIONS_LIVE" in os.environ:
        app.config["DETECTIONS_LIVE"] = (os.getenv("OCCT_DETECTIONS_LIVE") == "1")
    app.config["BRUTE_4625_THRESHOLD"]   = env_int("OCCT_BRUTE_4625_THRESHOLD",   app.config["BRUTE_4625_THRESHOLD"])
    app.config["DETECTIONS_INTERVAL"]     = env_int("OCCT_DETECTIONS_INTERVAL",     app.config["DETECTIONS_INTERVAL"])
    app.config["DETECTIONS_LOOKBACK_MIN"] = env_int("OCCT_DETECTIONS_LOOKBACK_MIN", app.config["DETECTIONS_LOOKBACK_MIN"])
    app.config["DETECTIONS_EVENT_IDS"]    = env_csv_int("OCCT_DETECTIONS_EVENT_IDS", app.config["DETECTIONS_EVENT_IDS"])
    app.config["DETECTIONS_DEDUPE_SEC"]   = env_int("OCCT_DETECTIONS_DEDUPE_SEC",   app.config["DETECTIONS_DEDUPE_SEC"])

# ---------------------------------- Flask app ---------------------------------

app = Flask(
    __name__,
    template_folder="../frontend",
    static_folder="../frontend",
    static_url_path="",
    instance_relative_config=True,
)

# Ensure instance/ exists early
os.makedirs(app.instance_path, exist_ok=True)

# Apply sane defaults, then create + load instance settings (if any)
apply_default_config(app)
ensure_instance_settings_file(app)
app.config.from_pyfile("settings.py", silent=True)

# Sessions
app.config["SECRET_KEY"] = os.getenv("OCCT_SECRET_KEY", "dev-secret-change-me")
app.config["SESSION_COOKIE_NAME"] = "occt_session"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# SQLite
db_path = os.path.join(app.instance_path, "occt.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
with app.app_context():
    db.create_all()
    ensure_c1_columns()
    ensure_unique_index()
    # Leave ensure_event_tables() out to avoid quoting issues on reserved names like "when".
    # Apply safe PRAGMAs for better concurrency.
    try:
        from sqlalchemy import text
        with db.engine.connect() as con:
            con.execute(text('PRAGMA journal_mode=WAL'))
            con.execute(text('PRAGMA synchronous=NORMAL'))
            con.execute(text('PRAGMA busy_timeout=5000'))
    except Exception as e:
        print(f'[sqlite] pragma set failed: {e}')

# Blueprints + APIs
from .api import api_bp, sample_bp, live_bp
start_live_poller_if_enabled(app)               # start background poller if enabled
attach_live_facts(live_bp, app)                 # live facts endpoint
attach_live_compliance(live_bp, app)            # live compliance stats endpoint
attach_live_rules_api(live_bp, app)             # live rules management endpoints
attach_live_rules_api(sample_bp, app)           # also expose rules mgmt for sample
attach_live_runner_api(live_bp, app)            # live runner endpoints
attach_detections_api(sample_bp, live_bp, app)  # detections endpoints (both modes)

app.register_blueprint(sample_bp)               # /api/sample/*
app.register_blueprint(api_bp)                  # /api/*
app.register_blueprint(live_bp)                 # /api/live/*

# ------------------------------- Auth + pages ---------------------------------

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
        # keep original redirect target for compatibility
        return redirect(url_for("index")) if "index" in app.view_functions else redirect(url_for("home_page"))
    return render_template("login.html")

@app.post("/auth/login")
def auth_login():
    data = request.get_json(silent=True) or {}
    u = (data.get("username") or "").strip()
    p = data.get("password") or ""
    if u == ADMIN_USER and p == ADMIN_PASS:
        session["user"] = u
        return jsonify(ok=True, redirect=url_for("home_page"))
    return jsonify(ok=False, error="invalid"), 401

@app.post("/auth/logout")
def auth_logout():
    session.clear()
    return jsonify(ok=True)

@app.get("/logout")
def do_logout_alias():
    session.clear()
    return redirect(url_for("login_page"))

@app.get("/auth/logout")
def do_logout_canonical():
    session.clear()
    return redirect(url_for("login_page"))

@app.get("/api/live/has-scan")
def api_live_has_scan():
    count = db.session.query(func.count(AuditEvent.id)).filter_by(source="live").scalar() or 0
    last_time = db.session.query(func.max(AuditEvent.time)).filter_by(source="live").scalar()
    return jsonify({
        "has_scan": count > 0,
        "count": int(count),
        "last_time": last_time.isoformat() if last_time else None
    })

# Protected pages
@app.get("/home")
@login_required
def home_page():
    return render_template("home.html")

@app.get("/")
def root_redirect():
    if session.get("user"):
        return redirect(url_for("home_page"))
    return redirect(url_for("login_page"))

@app.get("/index")
@login_required
def dashboard_page():
    return render_template("index.html")

@app.get("/detections")
@login_required
def detections_page():
    return render_template("detections.html")

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

# -------------------------------- Entry point ---------------------------------

if __name__ == "__main__":
    import sys, subprocess, os

    # Run samples ingest ONCE before starting server
    try:
        is_reloader_child = (os.environ.get("WERKZEUG_RUN_MAIN") == "true")
        not_using_reloader = (os.environ.get("WERKZEUG_RUN_MAIN") is None)
        if is_reloader_child or not_using_reloader:
            subprocess.run([sys.executable, "-m", "backend.ingest_samples"], check=True)
            print("[auto-ingest] backend.ingest_samples completed")
    except Exception as e:
        print(f"[auto-ingest] failed: {e}")

    # IMPORTANT: threaded=True so SSE doesn't block other requests.
    # Keep your existing behaviour; if you want to avoid dual-PID logs, add use_reloader=False.
    app.run(debug=True, threaded=True, port=5000, use_reloader=False)
