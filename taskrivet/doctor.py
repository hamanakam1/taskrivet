"""Setup checks. Starts nothing, writes nothing, and calls no model."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import sqlite3
import stat
import sys
import time
from typing import Any, Mapping

from . import config as settings
from .core import SCHEMA_VERSION
from .launchers import catalog
from .loop import ENV, sessions_view
from .tickets import list_tickets


def _ledger(db: str | Path) -> tuple[str, str]:
    path = Path(db).expanduser()
    if not path.exists():
        return "warn", f"{path} does not exist yet. Run: taskrivet init"
    try:
        conn = sqlite3.connect(path, timeout=5)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return "fail", f"{path}: {exc}"
    status, detail = "ok", f"{path}: schema {version}, {tasks} tasks"
    if version < SCHEMA_VERSION:
        status, detail = "warn", detail + f"; it upgrades to schema {SCHEMA_VERSION} on the next ledger command"
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        status, detail = "warn", detail + f"; mode {oct(mode)} should be 0o600"
    return status, detail


def doctor(
    db: str | Path,
    *,
    config_path: str | Path | None = None,
    offline: bool = False,
    paths: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    environ = os.environ if environ is None else environ
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"check": name, "status": status, "detail": detail})

    add("python", "ok" if sys.version_info >= (3, 11) else "fail", "Python " + platform.python_version())
    path = Path(config_path).expanduser() if config_path else settings.config_path()
    cfg: dict[str, Any] = {}
    try:
        cfg = settings.load(path)
        add("config", "ok" if path.exists() else "warn",
            str(path) if path.exists() else f"{path} does not exist yet; defaults apply")
    except ValueError as exc:
        add("config", "fail", str(exc))

    origin = (cfg.get("ticket_service") or {}).get("origin")
    if not origin:
        add("ticket_service", "warn",
            "Not configured. Run: taskrivet config set ticket_service.origin http://127.0.0.1:PORT")
    elif offline:
        add("ticket_service", "skipped", f"{origin} (not contacted)")
    else:
        try:
            listing = list_tickets(origin, limit=1, timeout=min(10, settings.ticket_timeout(cfg)))
            total = listing["source_total"]
            add("ticket_service", "warn" if listing["stale"] else "ok",
                f"{origin} answered; {'unknown' if total is None else total} tickets;"
                f" freshness {'stale or unknown' if listing['stale'] else 'current'}")
        except (ValueError, OSError) as exc:
            add("ticket_service", "unavailable", f"{origin}: {exc}")

    add("ledger", *_ledger(db))

    service = sessions_view(db)
    if service["service"] == "running":
        add("session_service", "ok", f"{service['implementation']} service, pid {service['pid']},"
                                     f" {len(service['terminals'])} terminals")
    elif service["service"] == "not running":
        add("session_service", "ok", "Not running; it starts on demand")
    else:
        add("session_service", "fail", service.get("error") or "unavailable")
    add("terminal_launch", "ok" if os.access(ENV, os.X_OK) else "fail", ENV)

    rows = catalog(cfg, paths)
    ready = [r["tool"] for r in rows if r["status"] == "ready"]
    add("launchers", "ok" if ready else "warn",
        f"{len(ready)} ready: " + ", ".join(ready) if ready else "No agent CLI found in scanned locations")

    adapter = (cfg.get("ticket_adapter") or {}).get("argv")
    if not adapter:
        add("ticket_adapter", "warn", "Not configured. Report previews work; posting needs ticket_adapter.argv.")
    else:
        exe = Path(adapter[0]).expanduser()
        usable = exe.is_file() and os.access(exe, os.X_OK)
        add("ticket_adapter", "ok" if usable else "fail", str(exe) + ("" if usable else " is not an executable file"))

    root = settings.runs_root(cfg)
    if not root.exists():
        add("runs", "ok", f"{root} is created on the first run")
    else:
        st = root.lstat()
        private = stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not st.st_mode & 0o077
        add("runs", "ok" if private else "fail", str(root) + ("" if private else " must be a folder you own with mode 0700"))

    if environ.get("TASKRIVET_SESSION"):
        add("agent_session", "warn",
            "TASKRIVET_SESSION is set: this shell belongs to an agent run, so handback --confirm is refused here")

    statuses = {c["status"] for c in checks}
    overall = "fail" if "fail" in statuses else "warn" if statuses & {"warn", "unavailable"} else "ok"
    return {"status": overall, "checks": checks, "observed_at": time.time(),
            "note": "Checks only. Nothing was started or written."}
