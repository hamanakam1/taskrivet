"""Operator-driven ticket loop: import, launch, and report back.

Nothing here chooses work. The operator names the ticket and the agent. Holds
are shown and must be acknowledged before a launch; acknowledging records the
operator's decision and clears nothing. Taskrivet never changes a ticket's
stage, tags, or holds. The only ticket write is a report the operator
confirms, sent through the operator's own adapter and checked by reading it
back.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
from typing import Any, Callable, Mapping

from . import config as settings
from .core import Conflict, Ledger
from .launchers import render, resolve
from .session_client import SCRUBBED, ServiceNotRunning, SessionClient, SessionError, session_dir, summarize
from .tickets import clip, get_ticket

ENV = "/usr/bin/env"
MAX_ARGS = 64
DEFAULT_LEASE = 4 * 3600
REPORT_BYTES = 4000
ADAPTER_OUTPUT = 1_000_000
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
NO_ACCEPTANCE = "Not stated on the ticket. Ask the operator before treating the work as done."
NO_ADAPTER = ("No ticket adapter is configured. Set ticket_adapter.argv in the private config;"
              " see docs/ticket-loop.md for the adapter protocol.")
STATE_TEXT = {
    "ready": "ready, no active session",
    "running": "running",
    "blocked": "blocked; the operator must reconcile it",
    "review": "finished; awaiting operator review",
    "accepted": "accepted by the operator in Taskrivet",
    "cancelled": "cancelled",
}


class HoldsPending(Conflict):
    """A launch needs the operator to acknowledge the ticket's holds first."""

    def __init__(self, key: str, holds: list[str]) -> None:
        super().__init__(
            f"Ticket {key} has {len(holds)} unacknowledged hold(s). Review them, then re-run with --ack."
            " Acknowledging records your decision; it clears nothing.")
        self.details = {"ticket": key, "holds": holds}


class AdapterError(OSError):
    """The ticket adapter failed or its outcome is unknown."""


class HandbackUnconfirmed(OSError):
    def __init__(self, message: str, record: dict[str, Any]) -> None:
        super().__init__(message)
        self.details = {"handback": {k: record.get(k) for k in ("id", "status", "attempts", "last_error", "marker")}}


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def cli_prefix() -> str:
    """How an agent terminal can reach this same command line."""
    if shutil.which("taskrivet"):
        return "taskrivet"
    root = Path(__file__).resolve().parent.parent
    return f"PYTHONPATH={shlex.quote(str(root))} {shlex.quote(sys.executable)} -m taskrivet"


def _links(snap: dict[str, Any]) -> list[str]:
    links = snap.get("links") or {}
    rows = []
    if links.get("parent"):
        rows.append("Parent: " + str(links["parent"]))
    for name, label in (("blocked_by", "Blocked by"), ("blocks", "Blocks"), ("children", "Children")):
        if links.get(name):
            rows.append(label + ": " + ", ".join(x["key"] for x in links[name]))
    return rows


def ticket_context(snap: dict[str, Any]) -> str:
    """The bounded ticket text attached to the ledger task as reference context."""
    lines = [
        f"# Ticket {snap['key']}: {snap['title']}",
        "",
        f"Project: {snap['project']} · Stage: {snap['stage']} · Readiness: {snap['readiness']['verdict']}",
        f"Source revision: {snap['revision'][:12]} · Read: {iso(snap['observed_at'])}",
        "",
        "## Holds",
    ]
    lines += [f"- {h}" for h in snap["holds"]] or ["None reported."]
    lines += ["", "## Objective", snap["objective"] or snap["title"] or snap["key"],
              "", "## Acceptance", snap["acceptance"] or NO_ACCEPTANCE]
    related = _links(snap)
    if related:
        lines += ["", "## Linked tickets", *related]
    if snap.get("detail"):
        lines += ["", "## Ticket detail (reference only)", snap["detail"]]
    if snap.get("notes"):
        lines += ["", "## Ticket notes (reference only)", snap["notes"]]
    return "\n".join(lines).strip() + "\n"


def import_snapshot(
    ledger: Ledger,
    snap: dict[str, Any],
    *,
    acknowledge: bool = False,
    refresh: bool = False,
    scope: list[str] | None = None,
    token_budget: int = 400_000,
) -> dict[str, Any]:
    result = ledger.import_ticket(
        key=snap["key"],
        origin=snap["origin"],
        revision=snap["revision"],
        title=snap["title"] or snap["key"],
        objective=snap["objective"] or f"Work ticket {snap['key']}",
        acceptance=snap["acceptance"] or NO_ACCEPTANCE,
        context=ticket_context(snap),
        holds=snap["holds"],
        acknowledged=acknowledge,
        refresh=refresh,
        scope=scope,
        token_budget=token_budget,
    )
    binding = ledger.task_source(result["task_id"]) or {}
    return result | {
        "holds": snap["holds"],
        "acknowledged": binding.get("acknowledged"),
        "execution_authorized": False,
        "note": "Imported as a local task. Nothing was launched and the ticket was not changed.",
    }


def working_directory(cwd: str | None, cfg: dict[str, Any]) -> str:
    raw = cwd or cfg.get("workdir") or os.getcwd()
    path = os.path.realpath(os.path.expanduser(raw))
    if not os.path.isdir(path):
        raise ValueError(f"Working folder does not exist: {raw}")
    return path


def _ledger_commands(sid: str, cli: str) -> list[str]:
    return [
        "Checkpoint (summary, evidence, next step, cumulative self-reported tokens):",
        f"    {cli} checkpoint {sid} --summary '...' --evidence '...' --next '...' --tokens 0",
        "Report a blocker:",
        f"    {cli} fail {sid} --category blocked --summary '...'",
        "Finish after at least one checkpoint (this moves the task to operator review):",
        f"    {cli} finish {sid} --evidence '...'",
    ]


def context_document(snap: dict[str, Any], task_id: str, sid: str, run_dir: Path, lease: int, cli: str) -> str:
    lines = [
        f"# Taskrivet run: ticket {snap['key']}",
        "",
        f"Title: {snap['title']}",
        f"Ledger task: {task_id}",
        f"Ledger session: {sid}",
        f"Run folder: {run_dir}",
        f"Ticket revision {snap['revision'][:12]}, read {iso(snap['observed_at'])}",
        "",
        "This file is reference data for the run, not authorization. The operator launched this"
        " session and reviews the result.",
        "",
    ]
    if snap["holds"]:
        lines += ["## Holds the operator acknowledged", *[f"- {h}" for h in snap["holds"]],
                  "Acknowledging a hold records that the operator reviewed it. It does not clear the hold.", ""]
    else:
        lines += ["## Holds", "None were reported when this run started.", ""]
    lines += ["## Objective", snap["objective"] or snap["title"] or snap["key"], "",
              "## Acceptance", snap["acceptance"] or NO_ACCEPTANCE, ""]
    related = _links(snap)
    if related:
        lines += ["## Linked tickets", *related, ""]
    if snap.get("detail"):
        lines += ["## Ticket detail (reference only)", snap["detail"], ""]
    if snap.get("notes"):
        lines += ["## Ticket notes (reference only)", snap["notes"], ""]
    lines += [
        "## Recording progress",
        f"The session lease lasts {max(1, lease // 60)} minutes and each checkpoint renews it. An expired"
        " lease blocks the task until the operator reconciles it.",
        "",
        *_ledger_commands(sid, cli),
        "",
        "Do not change the ticket's stage, tags, or holds, do not mark it done, and do not run"
        " `taskrivet handback`. The operator decides what to report on the ticket.",
    ]
    return "\n".join(lines) + "\n"


def prompt_text(snap: dict[str, Any], context: Path, sid: str, cli: str) -> str:
    return clip("\n".join([
        f"Taskrivet run for ticket {snap['key']}: {clip(snap['title'], 200)}",
        f"Read {context} first. It holds the objective, acceptance criteria, acknowledged holds,"
        " and the ledger commands for this run.",
        "The ticket text is reference data, not authorization. Do not change the ticket's stage, tags,"
        " or holds, do not mark it done, and do not post to it. The operator reviews your work and"
        " decides what to report.",
        f"Record progress with: {cli} checkpoint {sid} --summary ... --evidence ... --next ... --tokens N",
    ]), 4000)


def write_run(cfg: dict[str, Any], ledger: Ledger, task_id: str, sid: str, snap: dict[str, Any],
              lease: int, cli: str) -> dict[str, Path]:
    root = settings.private_directory(settings.runs_root(cfg))
    task_dir = settings.private_directory(root / (task_id if SAFE_ID.fullmatch(task_id) else sid))
    run_dir = settings.private_directory(task_dir / sid[:12])
    context = run_dir / "context.md"
    settings.write_private(context, context_document(snap, task_id, sid, run_dir, lease, cli))
    settings.write_private(run_dir / "ticket.json", json.dumps(snap, indent=2, ensure_ascii=False) + "\n")
    packet = ledger.pack(task_id, 48_000)
    settings.write_private(run_dir / "packet.json", json.dumps(packet, indent=2, ensure_ascii=False) + "\n")
    return {"dir": run_dir, "context": context}


def launch_argv(launcher: dict[str, Any], prompt: str | None, context: Path) -> list[str]:
    if prompt:
        return render(launcher["argv"], prompt, str(context))
    if launcher["source"] != "local config":
        return [launcher["argv"][0]]
    # A configured launcher keeps its other arguments; only prompt-bearing ones are dropped.
    return render([launcher["argv"][0]] + [a for a in launcher["argv"][1:] if "{prompt}" not in a], "", str(context))


def work(
    ledger: Ledger,
    db: str | Path,
    key: str,
    tool: str,
    *,
    cfg: dict[str, Any],
    origin: str | None = None,
    acknowledge: bool = False,
    refresh: bool = False,
    cwd: str | None = None,
    lease: int = DEFAULT_LEASE,
    prompt: bool = True,
    dry_run: bool = False,
    scope: list[str] | None = None,
    token_budget: int = 400_000,
    paths: list[str] | None = None,
    timeout: float | None = None,
    client_factory: Callable[[Path], SessionClient] = SessionClient,
) -> dict[str, Any]:
    """Import one operator-chosen ticket, start a ledger session, and open the agent in a terminal."""
    if type(lease) is not int or not 60 <= lease <= 7 * 86400:
        raise ValueError("Lease must be 60 seconds to 7 days")
    snap = get_ticket(settings.ticket_origin(cfg, origin), key, timeout or settings.ticket_timeout(cfg))
    launcher = resolve(tool, cfg, paths)
    workdir = working_directory(cwd, cfg)
    binding = ledger.ticket_binding(snap["key"])
    earlier = (binding or {}).get("acknowledged") or []
    if not acknowledge and any(h not in earlier for h in snap["holds"]):
        raise HoldsPending(snap["key"], snap["holds"])
    if "=" in launcher["argv"][0]:
        raise ValueError("Launcher path must not contain '='")
    if not os.access(ENV, os.X_OK):
        raise ValueError(f"{ENV} is required to launch agents")
    if 5 + len(launcher["argv"]) > MAX_ARGS:
        raise ValueError("Launcher has too many arguments")
    with_prompt = prompt and launcher["prompt"]
    plan = {
        "ticket": {k: snap[k] for k in ("key", "title", "stage", "project", "revision")}
        | {"url": settings.ticket_link(cfg, snap["key"])},
        "holds": snap["holds"],
        "tool": tool,
        "launcher": {"source": launcher["source"], "executable": launcher["argv"][0], "prompt": with_prompt},
        "cwd": workdir,
        "lease_seconds": lease,
        "existing_task": (binding or {}).get("task_id"),
    }
    if dry_run:
        return plan | {
            "dry_run": True,
            "note": "Nothing was imported, started, or launched.",
            "next": f"taskrivet work {snap['key']} --tool {tool}" + (" --ack" if snap["holds"] else ""),
        }
    imported = import_snapshot(ledger, snap, acknowledge=acknowledge, refresh=refresh, scope=scope,
                               token_budget=token_budget)
    task_id = imported["task_id"]
    try:
        sid = ledger.start(task_id, f"taskrivet-work:{tool}", lease)["session_id"]
    except Conflict as exc:
        raise Conflict(f"{exc}. Ticket {snap['key']} is bound to task {task_id}; see taskrivet links --ticket"
                       f" {snap['key']}, then attach to its terminal or decide the task (retry, accept, or cancel)."
                       ) from None
    cli = cli_prefix()
    try:
        run = write_run(cfg, ledger, task_id, sid, snap, lease, cli)
        text = prompt_text(snap, run["context"], sid, cli) if with_prompt else None
        env_args = [f"TASKRIVET_TASK={task_id}", f"TASKRIVET_SESSION={sid}", f"TASKRIVET_TICKET={snap['key']}",
                    f"TASKRIVET_CONTEXT={run['context']}", f"TASKRIVET_RUN={run['dir']}"]
        client = client_factory(session_dir(db))
        try:
            hello = client.connect(start=True)
            terminal = client.request("create", {
                "cwd": workdir, "shell": ENV, "args": env_args + launch_argv(launcher, text, run["context"]),
                "task": task_id, "session": sid, "title": clip(f"{tool} · {snap['key']}", 200),
                "kind": "agent", "ref": snap["key"], "db": os.path.abspath(os.path.expanduser(str(db))),
            })
        finally:
            client.close()
    except BaseException as exc:
        summary = clip(str(exc) or type(exc).__name__, 300)
        if isinstance(exc, SessionError):
            summary = "Terminal start outcome unknown: " + summary + " Check taskrivet sessions before retrying."
        try:
            ledger.fail(sid, "terminal_start", summary)
        except (ValueError, sqlite3.Error):
            pass
        raise
    ledger.record("agent.launched", task_id, tool=tool, terminal=terminal["id"], session=sid,
                  ticket=snap["key"], launcher=launcher["source"], prompt=bool(text))
    return plan | {
        "task_id": task_id,
        "session_id": sid,
        "created_task": imported["created"],
        "acknowledged": imported["acknowledged"],
        "terminal": summarize(terminal),
        "service": hello.get("service") or "desktop",
        "context": str(run["context"]),
        "run_dir": str(run["dir"]),
        "attach": f"taskrivet attach {terminal['id']}",
        "note": "Launched at the operator's request. The ticket was not claimed or changed.",
    }


# -- reporting back ---------------------------------------------------------

def handback_task(ledger: Ledger, target: str) -> str:
    """Accept a task id, or a ticket key for its most recent linked task."""
    try:
        ledger.task(target)
        return target
    except ValueError:
        tasks = ledger.ticket_tasks(target)
        if not tasks:
            raise ValueError(f"No task or linked ticket named {target}") from None
        return tasks[-1]


def report_body(ledger: Ledger, task_id: str, note: str | None = None) -> str:
    detail = ledger.detail(task_id)
    source = ledger.task_source(task_id)
    if source is None:
        raise ValueError(f"Task {task_id} is not linked to a ticket. Import one with: taskrivet ticket-import KEY")
    task = detail["task"]
    if not detail["sessions"] and not (note and note.strip()):
        raise ValueError("Nothing to report yet: this task has no recorded session and no --note was given")
    lines = [
        f"Taskrivet report for {source['ticket_key']} (local task {task_id})",
        "Local task state: " + STATE_TEXT.get(task["status"], task["status"]),
    ]
    session = detail["session"]
    if session:
        lines.append(f"Latest session: {session['status']}, owner {clip(session['owner'], 80)}")
    checkpoint = detail["checkpoints"][0] if detail["checkpoints"] else None
    if checkpoint:
        lines += ["Summary: " + clip(checkpoint["summary"], 800),
                  "Evidence: " + clip(checkpoint["evidence"], 1200),
                  "Next step: " + clip(checkpoint["next_step"], 400)]
    finished = next((e for e in detail["events"] if e["type"] == "session.finished"), None)
    if finished and finished["data"].get("evidence"):
        lines.append("Finish evidence: " + clip(finished["data"]["evidence"], 800))
    lines.append(f"Self-reported tokens: {task['reported_tokens']} (not measured billing)")
    if detail["failures"]:
        last = detail["failures"][0]
        lines.append(f"Recorded failures: {len(detail['failures'])}; latest {last['category']}: "
                     + clip(last["summary"], 300))
    if note and note.strip():
        lines.append("Operator note: " + clip(note.strip(), 1000))
    lines.append("This report does not accept the work or change the ticket's stage, tags, or holds.")
    return clip("\n".join(lines), REPORT_BYTES)


def adapter_call(cfg: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    spec = cfg.get("ticket_adapter") or {}
    argv = list(spec.get("argv") or [])
    if not argv:
        raise ValueError(NO_ADAPTER)
    argv[0] = str(Path(argv[0]).expanduser())
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
    try:
        done = subprocess.run(argv, input=json.dumps(request, ensure_ascii=False), capture_output=True,
                              text=True, timeout=spec.get("timeout", 30), env=env, check=False)
    except subprocess.TimeoutExpired:
        raise AdapterError("Ticket adapter timed out; outcome unknown") from None
    except OSError as exc:
        raise AdapterError(f"Ticket adapter could not start: {exc.strerror or exc}") from None
    if done.returncode != 0:
        raise AdapterError(f"Ticket adapter exited with status {done.returncode}: "
                           + clip(done.stderr.strip(), 300))
    if len(done.stdout) > ADAPTER_OUTPUT:
        raise AdapterError("Ticket adapter reply is too large")
    try:
        reply = json.loads(done.stdout)
    except ValueError:
        raise AdapterError("Ticket adapter returned invalid JSON") from None
    if not isinstance(reply, dict):
        raise AdapterError("Ticket adapter returned an unsupported reply")
    if reply.get("error"):
        raise AdapterError("Ticket adapter: " + clip(str(reply["error"]), 300))
    return reply


def _record(row: dict[str, Any]) -> dict[str, Any]:
    keep = ("id", "ticket_key", "marker", "status", "attempts", "last_error", "created", "updated", "delivered")
    return {k: row.get(k) for k in keep}


def handback(
    ledger: Ledger,
    target: str,
    *,
    cfg: dict[str, Any],
    confirm: bool = False,
    note: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Preview a ticket report, or post it after explicit confirmation.

    The marker stays the same across retries, so an earlier delivery whose
    reply was lost is found on the ticket before anything is posted again.
    """
    environ = os.environ if environ is None else environ
    task_id = handback_task(ledger, target)
    body = report_body(ledger, task_id, note)
    source = ledger.task_source(task_id) or {}
    key = source.get("ticket_key")
    configured = bool((cfg.get("ticket_adapter") or {}).get("argv"))
    if not confirm:
        return {
            "preview": True,
            "ticket": key,
            "task_id": task_id,
            "body": body,
            "adapter_configured": configured,
            "next": f"Review the text, then run: taskrivet handback {task_id} --confirm",
        }
    if environ.get("TASKRIVET_SESSION"):
        raise Conflict("Confirm reports from an operator shell. TASKRIVET_SESSION is set here,"
                       " so this looks like an agent session.")
    if not configured:
        raise ValueError(NO_ADAPTER)
    previous = ledger.handbacks(task_id)
    if previous and previous[-1]["status"] == "delivered" and previous[-1]["body"] == body:
        return {
            "ticket": key,
            "task_id": task_id,
            "delivered": True,
            "already_present": True,
            "readback": None,
            "handback": _record(previous[-1]),
            "body": previous[-1]["body"] + "\n\n" + previous[-1]["marker"],
            "note": "This exact report was already delivered, so nothing was posted.",
        }
    staged = ledger.stage_handback(task_id, body)
    message = staged["body"] + "\n\n" + staged["marker"]
    base = {"protocol": 1, "ticket": key, "marker": staged["marker"]}
    already = False
    try:
        if adapter_call(cfg, base | {"op": "find"}).get("found") is True:
            already = True
        else:
            posted = adapter_call(cfg, base | {"op": "post", "body": message, "sender": "Taskrivet", "role": "agent"})
            if posted.get("posted") is not True:
                raise AdapterError("Ticket adapter did not confirm the post")
            if adapter_call(cfg, base | {"op": "find"}).get("found") is not True:
                raise AdapterError("The report was sent but readback did not find it; outcome unknown."
                                   " Re-run to reconcile; the marker prevents a duplicate.")
    except AdapterError as exc:
        record = ledger.settle_handback(staged["id"], False, error=str(exc))
        raise HandbackUnconfirmed(str(exc), record) from None
    record = ledger.settle_handback(staged["id"], True,
                                    note="already on the ticket" if already else "posted and read back")
    return {
        "ticket": key,
        "task_id": task_id,
        "delivered": True,
        "already_present": already,
        "readback": True,
        "handback": _record(record),
        "body": message,
        "note": "Report only. The ticket's stage, tags, and holds were not changed.",
    }


# -- read views -------------------------------------------------------------

def sessions_view(db: str | Path, timeout: float = 5.0) -> dict[str, Any]:
    """Terminals in the session service for this ledger. Never starts the service."""
    directory = session_dir(db)
    client = SessionClient(directory, timeout=timeout)
    try:
        hello = client.connect(start=False)
        terminals = client.request("list") or []
    except ServiceNotRunning:
        return {"service": "not running", "directory": str(directory), "terminals": [],
                "note": "Terminals exist only while the service runs. It starts on demand."}
    except (SessionError, ValueError) as exc:
        return {"service": "unavailable", "directory": str(directory), "terminals": None, "error": str(exc)}
    finally:
        client.close()
    return {"service": "running", "implementation": hello.get("service") or "desktop", "pid": hello.get("pid"),
            "directory": str(directory), "terminals": [summarize(t) for t in terminals]}


def links_view(ledger: Ledger, db: str | Path, ticket: str | None = None, limit: int = 200,
               live: bool = True) -> dict[str, Any]:
    view = ledger.links(ticket, limit)
    service = sessions_view(db) if live else None
    terminals = None
    if service is not None and service["terminals"] is not None:
        terminals = {t["id"]: t for t in service["terminals"]}
    for row in view["links"]:
        agent = row.get("agent")
        if not agent or not agent.get("terminal"):
            continue
        if terminals is None:
            agent["terminal_state"] = None
        elif agent["terminal"] in terminals:
            agent["terminal_state"] = terminals[agent["terminal"]]["state"]
            agent["exit_code"] = terminals[agent["terminal"]]["exit_code"]
        else:
            agent["terminal_state"] = "gone"
    view["session_service"] = service["service"] if service else "not checked"
    return view
