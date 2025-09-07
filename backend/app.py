# backend/app.py
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
import os

app = Flask(
    __name__,
    template_folder="../frontend",
    static_folder="../frontend",
    static_url_path="",
    instance_relative_config=True,
)

# Ensure instance/ exists
os.makedirs(app.instance_path, exist_ok=True)

# SQLite (stays the same)
db_path = os.path.join(app.instance_path, "occt.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# --- NEW: register API blueprints ---
from .api import api_bp, sample_bp
app.register_blueprint(api_bp)
app.register_blueprint(sample_bp)

# --- Page routes (yours) ---
@app.get("/")
def index():
    return render_template("index.html")

@app.get("/audit")
def audit_page():
    return render_template("audit.html")

@app.get("/remediation")
def remediation_page():
    return render_template("remediation.html")

@app.get("/settings")
def settings_page():
    return render_template("settings.html")

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
