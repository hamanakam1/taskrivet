"""Synthetic fixtures: a local ticket service, an agent stand-in, and a report adapter.

Nothing here touches a real ticket service, account, or ticket.
"""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit

from taskrivet.session_client import SessionClient, SessionError


def ticket(key, **changes):
    t = {
        "key": key, "kind": "work", "id": 1, "title": f"Synthetic task {key}", "stage": "planned",
        "priority": 2, "owner": "", "project": "Example", "tags": [], "updated_at": "2026-01-01T00:00:00Z",
        "decision_brief": {"requires_human": False},
        "readiness": {"verdict": "READY", "verified": True, "stale": False},
        "detail": "Objective: Make the synthetic widget render.\nAcceptance: The widget test passes.\n",
        "notes": "", "chat_total": 0,
        "links_resolved": {"parent": None, "children": [], "blocked_by": [], "blocks": []},
    }
    t.update(changes)
    return t


class FakeTicketService:
    """GET-only stand-in for a local ticket service."""

    def __init__(self, tickets):
        self.tickets = {t["key"]: t for t in tickets}
        self.requests = []
        self.list_extra = {}
        self.status_code = 200
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def _summary(self, t):
        row = {k: v for k, v in t.items() if k not in ("detail", "notes", "links_resolved", "chat_total")}
        row["detail_head"] = (t.get("detail") or "")[:200]
        return row

    def _handler(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def reply(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                url = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                service.requests.append(("GET", url.path, query))
                if service.status_code != 200:
                    return self.reply(service.status_code, {"error": "synthetic outage"})
                if url.path == "/api/tix":
                    status = query.get("status", "all")
                    rows = [service._summary(t) for t in service.tickets.values()
                            if status == "all" or t["stage"] == status]
                    offset, limit = int(query.get("offset", 0)), int(query.get("limit", 50))
                    body = {"generated_at": datetime.now(timezone.utc).isoformat(), "stats": {"total": len(rows)},
                            "total": len(rows), "offset": offset, "limit": limit, "loading": False,
                            "refreshing": False, "stale": False, "refresh_error": None, "errors": [],
                            "tickets": rows[offset:offset + limit]}
                    body.update(service.list_extra)
                    return self.reply(200, body)
                if url.path == "/api/tix/ticket":
                    found = service.tickets.get(query.get("key"))
                    return self.reply(200, found if found else {"error": "not found"})
                return self.reply(404, {"error": "no route"})

            def do_POST(self):
                service.requests.append(("POST", self.path, {}))
                self.reply(405, {"error": "read only"})

        return Handler


TOOL = """#!/bin/sh
printf 'ARGS:%s\\n' "$*"
printf 'SESSION:%s\\n' "$TASKRIVET_SESSION"
printf 'TASK:%s\\n' "$TASKRIVET_TASK"
printf 'TICKET:%s\\n' "$TASKRIVET_TICKET"
printf 'CONTEXT:%s\\n' "$TASKRIVET_CONTEXT"
printf 'DB:%s\\n' "$TASKRIVET_DB"
printf 'PWD:%s\\n' "$(pwd -P)"
"""

ADAPTER = """import json, os, sys
path = sys.argv[1]
state = json.load(open(path)) if os.path.exists(path) else {"posts": [], "calls": [], "hide": 0}
request = json.load(sys.stdin)
state["calls"].append(request["op"])
if request.get("protocol") != 1:
    reply = {"error": "unsupported protocol"}
elif request["op"] == "find":
    found = any(request["marker"] in p["body"] for p in state["posts"] if p["ticket"] == request["ticket"])
    if found and state["hide"] > 0:
        state["hide"] -= 1
        found = False
    reply = {"found": found}
elif request["op"] == "post":
    state["posts"].append({k: request[k] for k in ("ticket", "body", "sender", "role")})
    reply = {"posted": True}
else:
    reply = {"error": "unsupported op"}
with open(path, "w") as f:
    json.dump(state, f)
print(json.dumps(reply))
"""


def write_tool(path):
    path = Path(path)
    path.write_text(TOOL)
    path.chmod(0o755)
    return path


def write_adapter(folder):
    path = Path(folder) / "adapter.py"
    path.write_text(ADAPTER)
    return path


def short_dir():
    """Unix socket paths are limited to about 100 bytes, so tests use /tmp."""
    return Path(tempfile.mkdtemp(prefix="trs-", dir="/tmp"))


def stop_service(directory):
    directory = Path(directory)
    client = SessionClient(directory, timeout=3)
    try:
        pid = client.connect(start=False)["pid"]
    except (SessionError, ValueError):
        return
    finally:
        client.close()
    os.kill(pid, signal.SIGTERM)
    for _ in range(50):
        if not (directory / "sessions.sock").exists():
            return
        time.sleep(0.05)


def wait_for_exit(directory, terminal_id, timeout=10):
    with SessionClient(directory) as client:
        client.connect(start=False)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = [t for t in client.request("list") if t["id"] == terminal_id]
            if found and found[0]["state"] == "exited":
                return found[0], "".join(c["data"] for c in found[0]["chunks"])
            time.sleep(0.05)
    raise AssertionError("terminal did not exit in time")


def cleanup(*paths):
    for path in paths:
        shutil.rmtree(path, ignore_errors=True)
