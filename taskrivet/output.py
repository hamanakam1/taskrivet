"""Plain-text views for --format table. JSON remains the stable interface."""
from __future__ import annotations

from datetime import datetime
import json
import shutil
from typing import Any, Callable

Column = tuple[str, Callable[[dict[str, Any]], Any], int]


def cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return " ".join(str(value).split())


def when(ts: Any) -> str:
    if type(ts) not in (int, float):
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def table(rows: list[dict[str, Any]], columns: list[Column]) -> str:
    width = shutil.get_terminal_size((120, 24)).columns
    cells = [[cell(get(r)) for _, get, _ in columns] for r in rows]
    widths = []
    for i, (header, _, limit) in enumerate(columns):
        longest = max([len(header)] + [len(c[i]) for c in cells])
        widths.append(min(longest, limit) if limit else longest)
    if columns and not columns[-1][2]:
        used = sum(widths[:-1]) + 2 * (len(widths) - 1)
        widths[-1] = max(12, min(widths[-1], width - used))

    def line(values: list[str]) -> str:
        out = []
        for value, w in zip(values, widths):
            out.append(value if len(value) <= w else value[:max(1, w - 1)] + "…")
        return "  ".join(v.ljust(w) for v, w in zip(out, widths)).rstrip()

    lines = [line([c[0] for c in columns])]
    lines += [line(c) for c in cells]
    if not rows:
        lines.append("(none)")
    return "\n".join(lines)


def block(pairs: list[tuple[str, Any]]) -> str:
    pad = max((len(k) for k, _ in pairs), default=0)
    return "\n".join(f"{k.ljust(pad)}  {cell(v)}" for k, v in pairs)


def bullets(title: str, items: list[Any]) -> list[str]:
    return [title] + ([f"  - {cell(i)}" for i in items] if items else ["  (none)"])


def _tickets(r: dict[str, Any]) -> str:
    total = "unknown" if r.get("source_total") is None else r["source_total"]
    head = (f"{r['returned']} shown of {total} · {r['origin']} · freshness "
            f"{'stale or unknown' if r.get('stale') else 'current'}")
    body = table(r["tickets"], [
        ("KEY", lambda t: t["key"], 24),
        ("STAGE", lambda t: t["stage"], 12),
        ("PRI", lambda t: t["priority"], 3),
        ("READINESS", lambda t: t["readiness"], 16),
        ("HOLDS", lambda t: len(t["holds"]), 5),
        ("TITLE", lambda t: t["title"], 0),
    ])
    tail = []
    if r.get("has_more"):
        q = r["query"]
        tail.append(f"More: --offset {q['offset'] + q['limit']}")
    return "\n".join([head, body, *tail])


def _local(rows: list[dict[str, Any]]) -> str:
    return table(rows, [
        ("TASK", lambda x: x["task_id"], 28),
        ("STATUS", lambda x: x["task_status"], 9),
        ("SESSION", lambda x: (x.get("session") or {}).get("status"), 9),
        ("AGENT", lambda x: (x.get("agent") or {}).get("tool"), 14),
        ("TERMINAL", lambda x: (x.get("agent") or {}).get("terminal_state"), 9),
        ("HANDBACK", lambda x: (x.get("handback") or {}).get("status"), 10),
        ("CHECKPOINT", lambda x: (x.get("checkpoint") or {}).get("summary"), 0),
    ])


def _ticket(r: dict[str, Any]) -> str:
    links = r.get("links") or {}
    parts = [block([
        ("Key", r["key"]), ("Title", r["title"]), ("Project", r["project"]), ("Stage", r["stage"]),
        ("Priority", r["priority"]), ("Owner", r["owner"] or None), ("Tags", ", ".join(r["tags"]) or None),
        ("Readiness", f"{r['readiness']['verdict']} (verified: {cell(r['readiness']['verified'])})"),
        ("Revision", r["revision"][:12]), ("Updated", r.get("source_updated_at")),
    ] + ([("Open", r["url"])] if r.get("url") else []))]
    parts.append("\n".join(bullets("Holds", r["holds"])))
    parts.append("Objective\n  " + cell(r.get("objective")))
    parts.append("Acceptance\n  " + cell(r.get("acceptance") or "not stated"))
    related = [f"blocked by {x['key']}" for x in links.get("blocked_by") or []]
    related += [f"blocks {x['key']}" for x in links.get("blocks") or []]
    if links.get("parent"):
        related.append(f"parent {links['parent']}")
    if related:
        parts.append("\n".join(bullets("Linked", related)))
    if r.get("local") is not None:
        parts.append("Local tasks\n" + _local(r["local"]))
    ack = " --ack" if r["holds"] else ""
    parts.append(f"Next\n  taskrivet ticket-import {r['key']}{ack}\n  taskrivet work {r['key']} --tool NAME{ack}")
    return "\n\n".join(parts)


def _import(r: dict[str, Any]) -> str:
    verb = "Created" if r["created"] else ("Refreshed" if r["refreshed"] else "Already imported as")
    lines = [f"{verb} task {r['task_id']} for ticket {r['ticket']} (revision {r['revision'][:12]})",
             *bullets("Holds", r["holds"]),
             "Acknowledged: " + ("yes" if r.get("acknowledged") else "no"), r["note"]]
    return "\n".join(lines)


def _ticket_route(r: dict[str, Any]) -> str:
    lines = [block([
        ("Ticket", r["ticket"]["key"]), ("Revision", r["ticket"]["revision"][:12] or None),
        ("Routing", r["status"]), ("Observed", when(r["observed_at"])),
        ("Source current", r["source_current"]),
        ("Expires", when(r["expires_at"])), ("Source", r["source"]),
        ("Execution authorized", False),
    ]), "", *bullets("Ticket and freshness holds", r["holds"]), "",
        *bullets("Routing evidence", r["reasons"])]
    for candidate in r["candidates"]:
        lines += ["", f"{cell(candidate['provider'])} / {cell(candidate['model'])}",
                  f"  Tool: {cell(candidate['tool'])}; cost: {cell(candidate['cost_class'])}; unranked",
                  *["  - " + cell(reason) for reason in candidate["reasons"]]]
    return "\n".join(lines)


def _work(r: dict[str, Any]) -> str:
    lines = [f"Ticket {r['ticket']['key']}: {r['ticket']['title']}", *bullets("Holds", r["holds"]),
             f"Tool: {r['tool']} ({r['launcher']['source']}; prompt {cell(r['launcher']['prompt'])})",
             f"Folder: {r['cwd']}"]
    if r.get("dry_run"):
        return "\n".join(lines + [r["note"], "Run: " + r["next"]])
    t = r["terminal"]
    lines += [f"Task {r['task_id']} · session {r['session_id']}",
              f"Terminal {t['id']} ({r['service']} service) is {t['state']}",
              f"Context: {r['context']}", f"Attach: {r['attach']}", r["note"]]
    return "\n".join(lines)


def _execution(r: dict[str, Any]) -> str:
    bound = r["binding"]
    lines = [block([("Task", bound["task_id"]), ("Ticket", bound["ticket_key"]),
                    ("Original source", bound["source_origin"]), ("Owner", bound["owner_origin"]),
                    ("Request", r.get("request_id")), ("State", r["status"]),
                    ("POST attempts", r.get("send_count")), ("Can submit", r.get("can_submit", False)),
                    ("Client authorizes execution", False), ("Source acceptance required", True)]),
             "", *bullets("Reasons", r["reason_codes"])]
    preflight = r.get("preflight")
    if preflight:
        route = preflight["route"]
        lines += ["", block([("Model", route["model"]), ("Engine", route["engine"]),
                              ("Cost class", route["cost_class"]), ("Qualification", route["qualification"])]),
                  "The owner validates its configured local inference binding on each call."]
    receipt = r.get("receipt")
    if receipt:
        lines += ["", block([("Owner run", receipt["run_id"]), ("Owner result", receipt["owner_result"])])]
    lines += ["", "A request or returned owner run does not establish accepted work. Unknown outcomes are never replayed."]
    return "\n".join(lines)


def _handback(r: dict[str, Any]) -> str:
    if r.get("preview"):
        adapter = "configured" if r["adapter_configured"] else "not configured"
        return "\n".join([f"Preview for ticket {r['ticket']} (task {r['task_id']}); adapter {adapter}", "",
                          r["body"], "", r["next"]])
    h = r["handback"]
    state = "already on the ticket" if r.get("already_present") else "posted and read back"
    return "\n".join([f"Report for ticket {r['ticket']} {state}.",
                      f"Handback {h['id']} · {h['status']} · attempts {h['attempts']}", r["note"]])


def _links(r: dict[str, Any]) -> str:
    head = f"Session service: {r.get('session_service')}"
    return head + "\n" + table(r["links"], [
        ("TICKET", lambda x: x["ticket_key"], 22),
        ("TASK", lambda x: x["task_id"], 28),
        ("STATUS", lambda x: x["task_status"], 9),
        ("SESSION", lambda x: (x.get("session") or {}).get("status"), 9),
        ("AGENT", lambda x: (x.get("agent") or {}).get("tool"), 14),
        ("TERMINAL", lambda x: (x.get("agent") or {}).get("terminal_state"), 9),
        ("HANDBACK", lambda x: (x.get("handback") or {}).get("status"), 10),
        ("TITLE", lambda x: x["title"], 0),
    ])


def _sessions(r: dict[str, Any]) -> str:
    if r["service"] != "running":
        return f"Session service: {r['service']}" + (f" ({r['error']})" if r.get("error") else "")
    head = f"Session service: running ({r['implementation']}, pid {r['pid']})"
    return head + "\n" + table(r["terminals"], [
        ("ID", lambda t: t["id"], 8),
        ("STATE", lambda t: t["state"] if t["exit_code"] is None else f"{t['state']}:{t['exit_code']}", 9),
        ("KIND", lambda t: t["kind"], 8),
        ("REF", lambda t: t["ref"], 18),
        ("TASK", lambda t: t["task"], 24),
        ("TITLE", lambda t: t["title"] or t["command"], 24),
        ("LAST LINE", lambda t: t["last_line"], 0),
    ])


def _doctor(r: dict[str, Any]) -> str:
    return f"Overall: {r['status']}\n" + table(r["checks"], [
        ("CHECK", lambda c: c["check"], 16), ("STATUS", lambda c: c["status"], 11), ("DETAIL", lambda c: c["detail"], 0),
    ])


def _launchers(r: dict[str, Any]) -> str:
    return table(r["launchers"], [
        ("TOOL", lambda x: x["tool"], 16), ("STATUS", lambda x: x["status"], 14), ("DETAIL", lambda x: x["detail"], 0),
    ])


def _status(r: dict[str, Any]) -> str:
    return table(r["tasks"], [
        ("TASK", lambda t: t["id"], 28), ("STATUS", lambda t: t["status"], 9), ("KIND", lambda t: t["kind"], 8),
        ("BUDGET", lambda t: t["token_budget"], 8), ("OBJECTIVE", lambda t: t["objective"], 0),
    ])


def _tools(r: dict[str, Any]) -> str:
    rows = [t for t in r["tools"] if t["category"] == "coding-agent"]
    return table(rows, [
        ("ID", lambda t: t["id"], 16), ("INSTALLED", lambda t: t["installed"], 9),
        ("NAME", lambda t: t["name"], 32), ("EXECUTABLE", lambda t: t["executable"], 0),
    ])


def event_line(e: dict[str, Any]) -> str:
    data = cell(e.get("data")) if e.get("data") else ""
    return f"{when(e.get('created'))}  #{e.get('seq')}  {e.get('type')}  {e.get('task_id') or '-'}  {data}".rstrip()


def _config(r: dict[str, Any]) -> str:
    if "settings" in r:
        state = "exists" if r["exists"] else "does not exist"
        return f"{r['path']} ({state})\n" + json.dumps(r["settings"], indent=2, sort_keys=True)
    if "value" in r:
        return cell(r["value"]) if not isinstance(r["value"], (dict, list)) else json.dumps(r["value"], indent=2)
    return generic(r)


def generic(r: Any) -> str:
    if isinstance(r, list):
        if r and all(isinstance(x, dict) for x in r):
            keys = list(dict.fromkeys(k for x in r for k in x))
            return table(r, [(k.upper(), (lambda x, k=k: x.get(k)), 40) for k in keys])
        return "\n".join(cell(x) for x in r)
    if isinstance(r, dict):
        return block([(k, v) for k, v in r.items()])
    return cell(r)


RENDERERS: dict[str, Callable[[Any], str]] = {
    "tickets": _tickets, "ticket": _ticket, "ticket-import": _import, "work": _work, "handback": _handback,
    "ticket-route": _ticket_route,
    "links": _links, "sessions": _sessions, "doctor": _doctor, "launchers": _launchers, "status": _status,
    "tools": _tools, "config": _config,
    "events": lambda r: "\n".join(event_line(e) for e in r) or "(none)",
}
RENDERERS.update({name: _execution for name in (
    "execution-preflight", "execution-prepare", "execution-inspect", "execution-submit", "execution-status", "execution-observe")})


def render(command: str, result: Any) -> str:
    return RENDERERS.get(command, generic)(result)
