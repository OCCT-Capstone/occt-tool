# backend/detections_api.py
from __future__ import annotations
import datetime as dt
from flask import Blueprint, request, jsonify, make_response
from sqlalchemy import func, desc
from .models import db, SecurityEvent, Detection

def _resp(obj, status=200):
    resp = make_response(jsonify(obj), status)
    resp.headers["Cache-Control"] = "no-store"
    return resp

def _normalize_int(value, default, lo=None, hi=None):
    try:
      v = int(value)
    except Exception:
      v = default
    if lo is not None: v = max(v, lo)
    if hi is not None: v = min(v, hi)
    return v

def _string_like(s): return f"%{(s or '').strip().lower()}%"

def attach_detections_api(sample_bp: Blueprint, live_bp: Blueprint, app):
    """
    Adds /events and /detections endpoints to sample & live blueprints.

    NOTE: SSE (/api/live/stream) and /api/live/notify/test are intentionally
    NOT defined here to avoid conflicts — they live in backend/api.py.
    """

    # ----------------- EVENTS (LIVE + SAMPLE) -----------------
    @live_bp.get("/events")
    def live_events():
        page  = _normalize_int(request.args.get("page", 1), 1, 1)
        pagesz= _normalize_int(request.args.get("pagesz", 20), 20, 1, 500)
        q = (request.args.get("q") or "").strip().lower()
        f_event_id = (request.args.get("event_id") or "").strip()
        f_account  = (request.args.get("account") or "").strip().lower()
        f_ip       = (request.args.get("ip") or "").strip().lower()

        s = db.session.query(SecurityEvent).filter(SecurityEvent.source == "live")
        if f_event_id:
            ids = [int(x) for x in f_event_id.split(",") if x.strip().isdigit()]
            if ids: s = s.filter(SecurityEvent.event_id.in_(ids))
        if f_account:
            s = s.filter(func.lower(SecurityEvent.account).like(_string_like(f_account)))
        if f_ip:
            s = s.filter(func.lower(SecurityEvent.ip).like(_string_like(f_ip)))
        if q:
            s = s.filter(
                func.lower(SecurityEvent.message).like(_string_like(q)) |
                func.lower(SecurityEvent.provider).like(_string_like(q))
            )
        s = s.order_by(desc(SecurityEvent.time), desc(SecurityEvent.record_id))
        total = s.count()
        rows = s.offset((page - 1) * pagesz).limit(pagesz).all()
        out = [{
            "id": r.id,
            "time": r.time.isoformat() + "Z" if r.time else None,
            "event_id": r.event_id,
            "account": r.account, "ip": r.ip, "message": r.message,
            "host": r.host, "channel": r.channel, "provider": r.provider,
        } for r in rows]
        return _resp({"total": total, "page": page, "pagesz": pagesz, "items": out})

    @sample_bp.get("/events")
    def sample_events():
        page  = _normalize_int(request.args.get("page", 1), 1, 1)
        pagesz= _normalize_int(request.args.get("pagesz", 20), 20, 1, 500)
        q = (request.args.get("q") or "").strip().lower()

        s = db.session.query(SecurityEvent).filter(SecurityEvent.source == "sample")
        if q:
            s = s.filter(
                func.lower(SecurityEvent.message).like(_string_like(q)) |
                func.lower(SecurityEvent.provider).like(_string_like(q))
            )
        s = s.order_by(desc(SecurityEvent.time), desc(SecurityEvent.record_id))
        total = s.count()
        rows = s.offset((page - 1) * pagesz).limit(pagesz).all()
        out = [{
            "id": r.id,
            "time": r.time.isoformat() + "Z" if r.time else None,
            "event_id": r.event_id,
            "account": r.account, "ip": r.ip, "message": r.message,
            "host": r.host, "channel": r.channel, "provider": r.provider,
        } for r in rows]
        return _resp({"total": total, "page": page, "pagesz": pagesz, "items": out})

    # ----------------- DETECTIONS (LIVE + SAMPLE) -----------------
    def _detections_common(source: str):
        page   = _normalize_int(request.args.get("page", 1), 1, 1)
        pagesz = _normalize_int(request.args.get("pagesz", 20), 20, 1, 500)
        f_sev   = (request.args.get("severity") or "").strip().lower()
        f_status= (request.args.get("status") or "").strip().lower()
        f_rule  = (request.args.get("rule") or "").strip()
        q       = (request.args.get("q") or "").strip().lower()

        s = db.session.query(Detection).filter(Detection.source == source)
        if f_sev:    s = s.filter(func.lower(Detection.severity) == f_sev)
        if f_status: s = s.filter(func.lower(Detection.status) == f_status)
        if f_rule:   s = s.filter(Detection.rule_id.like(f"%{f_rule}%"))
        if q:
            s = s.filter(
                func.lower(Detection.summary).like(_string_like(q)) |
                func.lower(Detection.evidence).like(_string_like(q))
            )
        s = s.order_by(desc(Detection.when), desc(Detection.id))
        total = s.count()
        rows = s.offset((page - 1) * pagesz).limit(pagesz).all()
        out = [{
            "id": r.id,
            "when": r.when.isoformat() + "Z" if r.when else None,
            "rule_id": r.rule_id,
            "severity": r.severity,
            "summary": r.summary,
            "account": r.account, "ip": r.ip,
            "host": r.host, "status": r.status,
            "evidence": r.evidence,
        } for r in rows]
        return {"total": total, "page": page, "pagesz": pagesz, "items": out}

    @live_bp.get("/detections")
    def live_detections():
        return _resp(_detections_common("live"))

    @sample_bp.get("/detections")
    def sample_detections():
        return _resp(_detections_common("sample"))
