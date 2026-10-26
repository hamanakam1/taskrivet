"""Operator-selected ticket reads from an explicitly configured local service.

GET only. Nothing here claims, edits, or advances a ticket. Holds are reported
so the operator can decide; Taskrivet never clears or overrides them.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any
from urllib.parse import urlencode

from .dashboard import execution_holds, fetch_json, freshness, local_origin, require_complete, tag_list

KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
STATUS = re.compile(r"^[a-z_]{1,32}$")
KINDS = ("work", "case", "decision", "all")
DETAIL_BYTES = 24_000
NOTES_BYTES = 8_000
LABELS = {
    "objective": re.compile(
        r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:objective|goal)(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.*)$", re.I),
    "acceptance": re.compile(
        r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:acceptance(?: criteria)?|done when)(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.*)$", re.I),
}


def clip(value: Any, limit: int) -> str:
    """Bound text by UTF-8 bytes and say so when anything was cut."""
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", "ignore") + "\n[truncated by Taskrivet]"


def check_key(key: Any) -> str:
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise ValueError("Ticket key must be 1-128 letters, digits, or _.:- characters")
    return key


def _readiness(t: dict[str, Any]) -> dict[str, Any]:
    return t.get("readiness") if isinstance(t.get("readiness"), dict) else {}


def _row(t: dict[str, Any]) -> dict[str, Any]:
    """Holds from the ticket itself; list freshness is reported once, at the top."""
    return {
        "key": t["key"],
        "title": clip(t.get("title"), 500),
        "kind": str(t.get("kind") or "unknown")[:32],
        "project": str(t.get("project") or "Unassigned")[:200],
        "stage": str(t.get("stage") or "unknown")[:64],
        "priority": t.get("priority") if type(t.get("priority")) is int else None,
        "owner": str(t.get("owner") or "")[:200],
        "tags": tag_list(t.get("tags")),
        "readiness": str(_readiness(t).get("verdict") or "UNKNOWN")[:128],
        "holds": execution_holds(t, False, str(t.get("detail_head") or "")),
        "source_updated_at": t.get("updated_at") if isinstance(t.get("updated_at"), str) else None,
    }


def list_tickets(
    origin: str,
    q: str | None = None,
    status: str = "all",
    kind: str = "work",
    limit: int = 50,
    offset: int = 0,
    timeout: float = 30,
    now: float | None = None,
) -> dict[str, Any]:
    base = local_origin(origin)
    if q is not None and (not isinstance(q, str) or len(q) > 200 or "\0" in q):
        raise ValueError("Search text must be at most 200 characters")
    if not isinstance(status, str) or not STATUS.fullmatch(status):
        raise ValueError("Status must be a lowercase source state such as planned or all")
    if kind not in KINDS:
        raise ValueError("Kind must be one of: " + ", ".join(KINDS))
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("Limit must be 1-200")
    if type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise ValueError("Offset must be 0-1000000")
    params: dict[str, Any] = {"status": status, "limit": limit, "offset": offset}
    if q:
        params["q"] = q
    payload = require_complete(fetch_json(base + "/api/tix?" + urlencode(params), timeout=timeout))
    stale, _age, observed = freshness(payload, now)
    rows = []
    for t in payload["tickets"]:
        if not isinstance(t, dict) or not isinstance(t.get("key"), str) or not KEY.fullmatch(t["key"]):
            continue
        if kind != "all" and t.get("kind") != kind:
            continue
        rows.append(_row(t))
    total = payload.get("total") if type(payload.get("total")) is int else None
    return {
        "source": "ticket-service",
        "origin": base,
        "observed_at": observed,
        "source_generated_at": payload.get("generated_at"),
        "stale": stale,
        "query": {"q": q, "status": status, "kind": kind, "limit": limit, "offset": offset},
        "source_total": total,
        "returned": len(rows),
        "has_more": None if total is None else offset + limit < total,
        "tickets": rows,
        "execution_authorized": False,
        "note": "Holds are shown for operator review. Taskrivet never clears or overrides them.",
    }


def get_ticket(origin: str, key: str, timeout: float = 30, now: float | None = None) -> dict[str, Any]:
    base = local_origin(origin)
    check_key(key)
    payload = fetch_json(base + "/api/tix/ticket?" + urlencode({"key": key, "seen": 0}), timeout=timeout)
    if not isinstance(payload, dict):
        raise ValueError("Unsupported ticket response")
    if payload.get("error"):
        if str(payload["error"]).strip().lower() == "not found":
            raise ValueError(f"Ticket {key} was not found")
        raise ValueError("Ticket service reported an incomplete read: " + str(payload["error"])[:200])
    if not isinstance(payload.get("key"), str) or not KEY.fullmatch(payload["key"]):
        raise ValueError("Ticket response has no usable key")
    # An alias can resolve to a canonical ticket, but the service must bind
    # that response to the exact key requested. Never import an unrelated
    # ticket merely because its returned identifier is syntactically valid.
    if payload["key"] != key and payload.get("requested_key") != key:
        raise ValueError("Ticket response does not match the requested key")
    return snapshot(payload, base, now)


def _link_keys(values: Any) -> list[dict[str, str]]:
    rows = []
    for item in values if isinstance(values, list) else []:
        if isinstance(item, dict) and isinstance(item.get("key"), str):
            rows.append({"key": item["key"][:128], "title": clip(item.get("title"), 200)})
        if len(rows) >= 20:
            break
    return rows


def snapshot(t: dict[str, Any], origin: str, now: float | None = None) -> dict[str, Any]:
    """A bounded, minimized view of one ticket and its current holds."""
    readiness = _readiness(t)
    raw_detail = t.get("detail") if isinstance(t.get("detail"), str) else ""
    holds = execution_holds(t, False, raw_detail)
    links = t.get("links_resolved") if isinstance(t.get("links_resolved"), dict) else {}
    blocked_by = _link_keys(links.get("blocked_by"))
    if blocked_by:
        holds.append("Blocking dependencies (state unknown): " + ", ".join(x["key"] for x in blocked_by[:5]))
    facet = t.get("acceptance")
    view = {
        "key": t["key"],
        "requested_key": t["requested_key"] if isinstance(t.get("requested_key"), str) else None,
        "title": clip(t.get("title"), 500),
        "kind": str(t.get("kind") or "unknown")[:32],
        "project": str(t.get("project") or "Unassigned")[:200],
        "stage": str(t.get("stage") or "unknown")[:64],
        "priority": t.get("priority") if type(t.get("priority")) is int else None,
        "owner": str(t.get("owner") or "")[:200],
        "tags": tag_list(t.get("tags")),
        "readiness": {
            "verdict": str(readiness.get("verdict") or "UNKNOWN")[:128],
            "verified": readiness.get("verified") is True,
            "stale": bool(readiness.get("stale")),
        },
        "needs_decision": bool(t.get("needs_decision")),
        "objective": extract(raw_detail, "objective") or clip(t.get("title"), 500) or None,
        "acceptance": extract(raw_detail, "acceptance"),
        "detail": clip(raw_detail, DETAIL_BYTES),
        "notes": clip(t.get("notes"), NOTES_BYTES),
        "acceptance_facet": (clip(json.dumps(facet, sort_keys=True, default=str), 4000)
                             if isinstance(facet, dict) and facet and not facet.get("error") else None),
        "links": {
            "parent": (links["parent"].get("key") if isinstance(links.get("parent"), dict) else None),
            "children": _link_keys(links.get("children")),
            "blocked_by": blocked_by,
            "blocks": _link_keys(links.get("blocks")),
        },
        "chat_total": t.get("chat_total") if type(t.get("chat_total")) is int else None,
        "source_updated_at": t.get("updated_at") if isinstance(t.get("updated_at"), str) else None,
        "revision": revision(t),
        "holds": holds,
        "origin": origin,
        "observed_at": now if now is not None else time.time(),
        "execution_authorized": False,
    }
    return view


def revision(t: dict[str, Any]) -> str:
    """Hash of the work definition only: stage, tags, and readiness are live holds."""
    basis = {
        "key": t.get("key"),
        "kind": t.get("kind"),
        "title": t.get("title") if isinstance(t.get("title"), str) else "",
        "detail": t.get("detail") if isinstance(t.get("detail"), str) else "",
    }
    return hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def extract(text: str, label: str) -> str | None:
    """Return a labelled line ("Objective: ...") or the block under an empty label."""
    pattern = LABELS[label]
    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        match = pattern.match(line)
        if not match:
            continue
        value = match.group(1).strip().strip("*").strip()
        if not value:
            follow: list[str] = []
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    if follow:
                        break
                    continue
                if any(p.match(nxt) for p in LABELS.values()):
                    break
                follow.append(nxt.strip())
                if len(follow) >= 12:
                    break
            value = "\n".join(follow)
        if value:
            return clip(value, 2000)
    return None
