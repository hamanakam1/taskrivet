"""Bounded GET-only Ticket Center preview. No ticket mutations or dispatch."""
import hashlib
import json
import time
from datetime import datetime
from urllib.parse import urlsplit, urlencode
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request
from typing import Any

MAX_BYTES = 8 * 1024 * 1024
STATES = ("planned", "backlog", "progress", "blocked", "show_tell")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise ValueError("Dashboard redirects are disabled")


def endpoint(base: str, state: str, offset: int) -> str:
    parsed = urlsplit(base)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("This adapter supports an explicit local HTTP dashboard only")
    if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Use a local dashboard origin without credentials, path, or query")
    if state not in STATES or type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise ValueError("Invalid ticket page")
    return base.rstrip("/") + "/api/tix?" + urlencode({"status": state, "limit": 100, "offset": offset})


def project_payload(payload: dict[str, Any], origin: str, state: str, offset: int, now: float | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("tickets"), list):
        raise ValueError("Unsupported dashboard response")
    if payload.get("error") or payload.get("errors") or payload.get("refresh_error"):
        raise ValueError("Dashboard reported incomplete source data; preview withheld")
    if payload.get("loading"):
        raise ValueError("Dashboard is still loading; refresh later")
    generated = payload.get("generated_at")
    observed = now if now is not None else time.time()
    try:
        age = observed - datetime.fromisoformat(str(generated).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        age = None
    stale = payload.get("stale") is not False or age is None or age < -60 or age > 300
    rows: list[dict[str, Any]] = []
    for t in payload["tickets"]:
        if not isinstance(t, dict) or t.get("kind") != "work":
            continue
        key = t.get("key")
        if not isinstance(key, str) or len(key) > 128:
            continue
        readiness = t.get("readiness") if isinstance(t.get("readiness"), dict) else {}
        tags = t.get("tags") or []
        if isinstance(tags, str):
            tags = tags.split(",")
        if not isinstance(tags, list):
            tags = []
        tags = [str(x)[:128] for x in tags[:100]]
        reasons: list[str] = []
        if stale:
            reasons.append("Source freshness is stale or unknown")
        if any(x.lower().replace("_", "-").strip() == "no-auto" for x in tags):
            reasons.append("No-auto execution hold")
        if t.get("needs_decision"):
            reasons.append("Operator decision required")
        if t.get("live") or t.get("executing") or t.get("stage") in ("active", "progress", "doing"):
            reasons.append("Already active or executing")
        if t.get("stage") in ("blocked", "done", "review", "show_tell"):
            reasons.append("Source stage requires reconciliation or review")
        if readiness.get("stale"):
            reasons.append("Readiness assessment is stale")
        verdict = str(readiness.get("verdict") or "UNKNOWN")
        if verdict.upper() != "READY":
            reasons.append("Readiness: " + verdict)
        if readiness.get("verified") is not True:
            reasons.append("Readiness is not verified")
        detail = str(t.get("detail_head") or "").lower()
        if "not authorized for autonomous execution" in detail:
            reasons.append("Explicit execution denial in source excerpt")
        reasons.extend(["Source claim and access grant not acquired", "Full context, dependencies, acceptance checks and tool entitlement not verified"])
        rows.append({
            "key": key,
            "title": str(t.get("title") or "")[:500],
            "project": str(t.get("project") or "Unassigned")[:200],
            "stage": str(t.get("stage") or "unknown")[:64],
            "priority": t.get("priority") if type(t.get("priority")) is int else None,
            "owner": str(t.get("owner") or "")[:200],
            "tags": tags,
            "readiness": verdict[:128],
            "reasons": reasons,
            "source_updated_at": t.get("updated_at"),
            "snapshot_hash": hashlib.sha256(json.dumps(t, sort_keys=True).encode()).hexdigest(),
            "execution_authorized": False,
        })
    rows.sort(key=lambda t: (t["priority"] if t["priority"] is not None else 99, t["key"]))
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    total = stats.get("total") if type(stats.get("total")) is int else None
    return {
        "adapter": "ticket-service",
        "mode": "preview-only",
        "origin": origin,
        "observed_at": observed,
        "source_generated_at": generated,
        "stale": stale,
        "source_status": state,
        "offset": offset,
        "limit": 100,
        "source_total": total,
        "returned": len(rows),
        "has_more": None if total is None else offset + 100 < total,
        "coverage": "One bounded source page; project filters apply only to returned work tickets.",
        "projects": sorted({t["project"] for t in rows}),
        "tickets": rows,
        "dispatch_enabled": False,
        "tool_selection": "Pending task context and capability qualification",
    }


def preview(base: str, state: str = "planned", offset: int = 0) -> dict[str, Any]:
    url = endpoint(base, state, offset)
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(Request(url, headers={"Accept": "application/json"}), timeout=10) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Dashboard response exceeds 8 MiB")
    return project_payload(json.loads(data), base, state, offset)