# backend/notify.py
from __future__ import annotations
import json
import threading
import time
from collections import deque
from typing import Dict, Any, Iterable
import os
import sys

# In-memory, REAL-TIME broadcaster (no DB replay, no 'id:' lines)

class _Client:
    def __init__(self) -> None:
        self.q = deque()                 # queue of payload dicts
        self.cv = threading.Condition()  # wait/notify

    def push(self, payload: Dict[str, Any]) -> None:
        with self.cv:
            self.q.append(payload)
            self.cv.notify()

_clients: set[_Client] = set()
_clients_lock = threading.Lock()

# Helpful identifiers to detect accidental duplicate module singletons
_BUS_ID = id(sys.modules[__name__])
_PID = os.getpid()

def _iter_events(client: _Client):
    """Yield SSE forever for this client. Only items queued AFTER connect are sent."""
    # identify the implementation on connect
    yield f": connected (occt-inmem-rt)\n\n"

    KEEPALIVE_SEC = 15
    last_ping = time.time()

    while True:
        payload = None
        with client.cv:
            if not client.q:
                # wait until either we get data or it’s time to ping
                remaining = max(0.0, KEEPALIVE_SEC - (time.time() - last_ping))
                client.cv.wait(timeout=remaining)
            if client.q:
                payload = client.q.popleft()

        if payload is not None:
            # No 'id:' lines -> browser won't send Last-Event-ID -> no replay
            data = json.dumps(payload, ensure_ascii=False)
            yield f"event: detection\ndata: {data}\n\n"
            continue

        # keepalive
        if time.time() - last_ping >= KEEPALIVE_SEC:
            last_ping = time.time()
            yield "event: ping\ndata: {}\n\n"

def sse_stream() -> Iterable[str]:
    """
    Server-Sent Events generator.
    - REAL-TIME ONLY: no replay, no DB reads, no 'id:' lines.
    """
    client = _Client()
    with _clients_lock:
        _clients.add(client)
    try:
        for chunk in _iter_events(client):
            yield chunk
    finally:
        with _clients_lock:
            _clients.discard(client)

def publish_detection(payload: Dict[str, Any]) -> int:
    """
    Push a detection to all connected SSE clients.
    Keys we expect: rule_id, summary, severity, account?, host?, ip?, when?
    """
    sent = 0
    with _clients_lock:
        targets = list(_clients)
    for c in targets:
        try:
            c.push(payload)
            sent += 1
        except Exception:
            pass
    return sent

# --------- DEBUG HELPERS (used by /api/live/debug/*) ---------
def _debug_state():
    with _clients_lock:
        return {
            "bus_id": _BUS_ID,
            "pid": _PID,
            "clients": len(_clients),
            "clients_set_id": id(_clients),
        }

def _debug_clear():
    # nothing buffered globally; return state
    return _debug_state()

# --------- Single-bus alias to avoid accidental duplicate modules ----------
# (Optional but safe: lets other modules import 'occt_sse_bus' and still get this singleton)
sys.modules.setdefault("occt_sse_bus", sys.modules[__name__])
