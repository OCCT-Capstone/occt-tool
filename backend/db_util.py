from sqlalchemy import text
from .models import db

def ensure_column(table: str, col: str, coltype: str, default_sql=None):
    with db.engine.connect() as con:
        cols = [r[1] for r in con.execute(text(f"PRAGMA table_info({table})")).all()]
        if col not in cols:
            con.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}"))
            if default_sql is not None:
                con.execute(text(f"UPDATE {table} SET {col}={default_sql} WHERE {col} IS NULL"))

def ensure_c1_columns():
    # Required for sample/live split
    ensure_column("audit_events", "source", "VARCHAR(16)", default_sql="'sample'")
    # Nice to have for per-host display (safe even if unused yet)
    ensure_column("audit_events", "host", "VARCHAR(128)")

def ensure_unique_index():
    """Ensure app-level idempotency even if multiple ingests fire."""
    sql = """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_audit_events_unique
    ON audit_events (source, time, category, control, outcome, account, description);
    """
    with db.engine.connect() as con:
        con.execute(text(sql))