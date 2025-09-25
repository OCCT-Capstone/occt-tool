# backend/live_runner.py
import os, json, time, queue, threading, subprocess, platform, shutil, uuid, datetime as dt
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from .models import db, AuditEvent
from .live_rules import evaluate_facts_document

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

def _is_windows():
    return platform.system().lower().startswith("windows")

def _find_powershell():
    if _is_windows():
        for cand in ("powershell.exe", "powershell"):
            path = shutil.which(cand)
            if path: return path
    for cand in ("pwsh.exe", "pwsh"):
        path = shutil.which(cand)
        if path: return path
    return None

def _project_root(app):
    return os.path.abspath(os.path.join(app.root_path, os.pardir))

def _rules_path(app):
    rules_dir = os.path.join(app.root_path, "rules")
    yml = os.path.join(rules_dir, "controls.yml")
    jsonp = os.path.join(rules_dir, "controls.json")
    if os.path.exists(yml): return yml
    if os.path.exists(jsonp): return jsonp
    return yml

def _load_collectors(app) -> List[Dict[str, Any]]:
    defaults = [
        {"name": "win_pwpolicy", "script": "collector/win_pwpolicy_facts.ps1", "interval_seconds": 600, "enabled": True, "replace_previous": True}
    ]
    cfg_path = os.path.join(app.root_path, "collectors.json")
    if not os.path.exists(cfg_path):
        return defaults
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        cols = data.get("collectors") or defaults
        return cols
    except Exception as ex:
        with app.app_context():
            app.logger.warning("Invalid collectors.json (%s). Using defaults.", ex)
        return defaults

def _safe_col_names() -> set:
    cols = set()
    try:
        rows = db.session.execute(text("PRAGMA table_info(audit_events)")).all()
        for r in rows:
            cols.add(r[1])
    except Exception:
        pass
    return cols

def _delete_previous_for_host(app, host: str):
    cols = _safe_col_names()
    where = "source = 'live'"
    params = {}
    if "host" in cols:
        where += " AND host = :host"
        params["host"] = host
    elif "account" in cols:
        where += " AND account = :host"
        params["host"] = host
    with app.app_context():
        db.session.execute(text(f"DELETE FROM audit_events WHERE {where}"), params)
        db.session.commit()

def _insert_events(app, rows: List[Dict[str, Any]]) -> int:
    inserted = 0
    with app.app_context():
        for r in rows:
            try:
                t = r.get("time")
                if isinstance(t, str):
                    s = t.strip().replace("Z", "")
                    try:
                        time_val = dt.datetime.fromisoformat(s) if "T" in s else dt.datetime.fromisoformat(s + "T00:00:00")
                    except Exception:
                        time_val = dt.datetime.utcnow()
                else:
                    time_val = dt.datetime.utcnow()

                evt = AuditEvent(
                    time=time_val,
                    category=(r.get("category") or "")[:64],
                    control=(r.get("control") or "")[:128],
                    outcome=(r.get("outcome") or "Info")[:32],
                    account=(r.get("account") or "")[:128],
                    description=(r.get("description") or "")[:4096],
                )
                try: evt.source = "live"
                except Exception: pass
                try: evt.host = (r.get("host") or "")[:128]
                except Exception: pass

                db.session.add(evt)
                inserted += 1
            except Exception as ex:
                app.logger.warning("Runner: skip bad row: %s", ex)
        db.session.commit()
    return inserted

def _summary_for_hosts(app, hosts: List[str]) -> Dict[str, int]:
    """Return counts across given hosts (LIVE only)."""
    cols = _safe_col_names()
    where = "source = 'live'"
    host_col = "host" if "host" in cols else ("account" if "account" in cols else None)
    total = 0
    failed = 0
    with app.app_context():
        if host_col is None:
            row = db.session.execute(text(f"""
                SELECT
                  COUNT(*) AS total,
                  SUM(CASE WHEN outcome='Failed' THEN 1 ELSE 0 END) AS failed
                FROM audit_events
                WHERE {where}
            """)).first()
            total += int(row[0] or 0)
            failed += int(row[1] or 0)
        else:
            for h in hosts:
                row = db.session.execute(text(f"""
                    SELECT
                      COUNT(*) AS total,
                      SUM(CASE WHEN outcome='Failed' THEN 1 ELSE 0 END) AS failed
                    FROM audit_events
                    WHERE {where} AND {host_col} = :h
                """), {"h": h}).first()
                total += int(row[0] or 0)
                failed += int(row[1] or 0)
    return {"total": total, "failed": failed}

class Runner:
    def __init__(self, app):
        self.app = app
        self.ps = _find_powershell()
        self.collectors = _load_collectors(app)
        self.rules_path = _rules_path(app)
        self.q: "queue.Queue" = queue.Queue()
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self._stop = threading.Event()
        self._started = False

    def start(self):
        if self._started:
            return self
        self._started = True
        threading.Thread(target=self._scheduler_loop, name="occt-runner-scheduler", daemon=True).start()
        threading.Thread(target=self._worker_loop, name="occt-runner-worker", daemon=True).start()
        with self.app.app_context():
            self.app.logger.info("Live runner started (ps=%s)", self.ps or "not found")
        return self

    def enqueue_immediate(self, names: Optional[List[str]] = None) -> str:
        names = names or [c["name"] for c in self.collectors if c.get("enabled", True)]
        job_id = "scan-" + uuid.uuid4().hex[:8]
        self.jobs[job_id] = {"job_id": job_id, "status": "queued", "submitted_at": time.time(), "names": names, "logs": []}
        self.q.put(("run_now", job_id, names))
        return job_id

    def status(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.jobs.get(job_id)

    def _scheduler_loop(self):
        next_at = {c["name"]: 0 for c in self.collectors}
        while not self._stop.is_set():
            now = time.time()
            for c in self.collectors:
                if not c.get("enabled", True): continue
                itv = max(int(c.get("interval_seconds", 600)), 30)
                if now >= next_at[c["name"]]:
                    self.enqueue_immediate([c["name"]])
                    next_at[c["name"]] = now + itv
            time.sleep(3)

    def _worker_loop(self):
        while not self._stop.is_set():
            try:
                kind, job_id, names = self.q.get(timeout=1)
            except queue.Empty:
                continue
            self._run_job(job_id, names)

    def _run_job(self, job_id: str, names: List[str]):
        self.jobs[job_id]["status"] = "running"
        ok_all = True
        for name in names:
            col = next((c for c in self.collectors if c["name"] == name), None)
            if not col:
                self.jobs[job_id]["logs"].append({name: {"ok": False, "error": "unknown_collector"}})
                ok_all = False
                continue
            res = self._run_collector(col)
            self.jobs[job_id]["logs"].append({name: res})
            ok_all = ok_all and bool(res.get("ok"))
        self.jobs[job_id]["finished_at"] = time.time()
        self.jobs[job_id]["status"] = "done" if ok_all else "error"

    def _run_collector(self, col: Dict[str, Any]) -> Dict[str, Any]:
        script = col.get("script")
        if not script:
            return {"ok": False, "error": "no_script"}
        if not os.path.isabs(script):
            script = os.path.join(_project_root(self.app), script)
        if not os.path.exists(script):
            return {"ok": False, "error": f"script_not_found:{script}"}
        if not self.ps:
            return {"ok": False, "error": "powershell_not_found"}

        args = [self.ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script]
        try:
            res = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 check=False, creationflags=CREATE_NO_WINDOW)
        except Exception as ex:
            return {"ok": False, "error": f"spawn_failed:{ex}"}

        if res.returncode != 0:
            return {"ok": False, "error": f"exit_{res.returncode}", "stderr": (res.stderr or "").strip()}

        stdout = (res.stdout or "").strip()
        if not stdout:
            return {"ok": False, "error": "no_stdout_json"}

        try:
            facts_doc = json.loads(stdout)
        except Exception as ex:
            return {"ok": False, "error": "json_parse_error", "detail": str(ex), "stdout_head": stdout[:400]}

        # Identify host (used for replace & summary)
        host = ""
        try:
            host = ((facts_doc.get("host") or {}).get("hostname") or facts_doc.get("hostname") or "").strip()
        except Exception:
            host = ""

        # Replace mode: clear previous LIVE rows for this host before inserting
        if col.get("replace_previous", False) and host:
            _delete_previous_for_host(self.app, host)

        # Evaluate + insert
        rows = evaluate_facts_document(facts_doc, _rules_path(self.app))
        inserted = _insert_events(self.app, rows)
        return {"ok": True, "inserted": inserted, "host": host}

# ---------- API attachment ----------

_runner_singleton = {"inst": None}
_routes_attached = False

def attach_live_runner_api(live_bp, app):
    global _routes_attached
    if _routes_attached:
        with app.app_context():
            app.logger.info("attach_live_runner_api: routes already attached; skipping.")
        return
    _routes_attached = True

    def _ensure_started():
        if _runner_singleton["inst"] is not None:
            return _runner_singleton["inst"]
        if os.environ.get("WERKZEUG_RUN_MAIN") == "false":
            _runner_singleton["inst"] = Runner(app)  # inert in parent
            return _runner_singleton["inst"]
        _runner_singleton["inst"] = Runner(app).start()
        return _runner_singleton["inst"]

    @live_bp.post("/rescan")
    def live_rescan():
        from flask import request as _request
        r = _ensure_started()
        body = _request.get_json(silent=True) or {}
        names = body.get("collectors")
        wait = body.get("wait") or (_request.args.get("wait") in ("1", "true", "yes"))

        job_id = r.enqueue_immediate(names)
        if not wait:
            return {"ok": True, "job_id": job_id, "status": "queued"}

        # Wait up to 25s for completion
        t0 = time.time()
        hosts = []
        inserted_total = 0
        while time.time() - t0 < 25:
            st = r.status(job_id) or {}
            if st.get("status") in ("done", "error"):
                # summarize
                for entry in (st.get("logs") or []):
                    for _, res in entry.items():
                        if res.get("ok"):
                            inserted_total += int(res.get("inserted") or 0)
                            h = (res.get("host") or "").strip()
                            if h: hosts.append(h)
                summary = _summary_for_hosts(app, hosts or [])
                total = summary["total"]
                failed = summary["failed"]
                return {
                    "ok": st.get("status") == "done",
                    "job_id": job_id,
                    "status": st.get("status"),
                    # fields your toast can read:
                    "ingested": inserted_total,
                    "unique": total,                # total rows after replace
                    "failed": failed,
                    # also include verbose field names, just in case
                    "inserted_total": inserted_total,
                    "failed_count": failed
                }
            time.sleep(0.3)

        # timeout but return partial info
        return {"ok": False, "job_id": job_id, "status": "pending", "message": "timeout_waiting"}

    @live_bp.get("/jobs/<job_id>")
    def live_job(job_id):
        r = _ensure_started()
        st = r.status(job_id)
        if not st:
            return {"error": "not_found"}, 404
        # short view + totals
        hosts = []
        inserted_total = 0
        for entry in (st.get("logs") or []):
            for _, res in entry.items():
                if res.get("ok"):
                    inserted_total += int(res.get("inserted") or 0)
                    h = (res.get("host") or "").strip()
                    if h: hosts.append(h)
        summary = _summary_for_hosts(app, hosts or [])
        return {
            **st,
            "inserted_total": inserted_total,
            "failed_count": summary["failed"],
        }
