"""Bounded GET-only Ticket Center preview. No ticket mutations or dispatch."""
import hashlib
import json
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlencode
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request
from typing import Any

MAX_BYTES = 8 * 1024 * 1024
STATES = ("planned", "backlog", "progress", "blocked", "show_tell")
CONTEXT_SCHEMA = "taskrivet.ticket-context.v1"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise ValueError("Dashboard redirects are disabled")


class SourceUnavailable(OSError):
    """The ticket service could not be read. Nothing is inferred from silence."""


def local_origin(base: Any) -> str:
    parsed = urlsplit(base if isinstance(base, str) else "")
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("This adapter supports an explicit local HTTP dashboard only")
    if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Use a local dashboard origin without credentials, path, or query")
    try:
        parsed.port
    except ValueError:
        raise ValueError("Use a local dashboard origin with a numeric port") from None
    return base.rstrip("/")


def endpoint(base: str, state: str, offset: int) -> str:
    origin = local_origin(base)
    if state not in STATES or type(offset) is not int or not 0 <= offset <= 1_000_000:
        raise ValueError("Invalid ticket page")
    return origin + "/api/tix?" + urlencode({"status": state, "limit": 100, "offset": offset})


def fetch_json(url: str, timeout: float = 10, max_bytes: int = MAX_BYTES) -> Any:
    """GET one local JSON document with proxies and redirects disabled."""
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(Request(url, headers={"Accept": "application/json"}), timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except HTTPError as exc:
        detail = ""
        try:
            body = json.loads(exc.read(65536) or b"{}")
            if isinstance(body, dict):
                detail = str(body.get("error") or "")[:200]
        except (ValueError, OSError):
            pass
        finally:
            exc.close()
        raise SourceUnavailable(f"Ticket service returned HTTP {exc.code}" + (": " + detail if detail else "")) from None
    except (URLError, TimeoutError, ConnectionError) as exc:
        raise SourceUnavailable(f"Ticket service unavailable: {getattr(exc, 'reason', exc)}") from None
    if len(data) > max_bytes:
        raise ValueError(f"Ticket service response exceeds {max_bytes} bytes")
    try:
        return json.loads(data)
    except ValueError:
        raise ValueError("Ticket service returned invalid JSON") from None


def require_complete(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("tickets"), list):
        raise ValueError("Unsupported dashboard response")
    if payload.get("error") or payload.get("errors") or payload.get("refresh_error"):
        raise ValueError("Dashboard reported incomplete source data; preview withheld")
    if payload.get("loading"):
        raise ValueError("Dashboard is still loading; refresh later")
    return payload


def freshness(payload: dict[str, Any], now: float | None = None) -> tuple[bool, float | None, float]:
    observed = now if now is not None else time.time()
    try:
        age = observed - datetime.fromisoformat(str(payload.get("generated_at")).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        age = None
    stale = payload.get("stale") is not False or age is None or age < -60 or age > 300
    return stale, age, observed


def tag_list(raw: Any) -> list[str]:
    tags = raw or []
    if isinstance(tags, str):
        tags = tags.split(",")
    if not isinstance(tags, list):
        return []
    return [str(x).strip()[:128] for x in tags[:100] if str(x).strip()]


def execution_holds(t: dict[str, Any], stale: bool, excerpt: str = "") -> list[str]:
    """Known reasons a ticket is not cleared for unattended execution."""
    readiness = t.get("readiness") if isinstance(t.get("readiness"), dict) else {}
    brief = t.get("decision_brief") if isinstance(t.get("decision_brief"), dict) else {}
    reasons: list[str] = []
    if stale:
        reasons.append("Source freshness is stale or unknown")
    if any(x.lower().replace("_", "-") == "no-auto" for x in tag_list(t.get("tags"))):
        reasons.append("No-auto execution hold")
    if t.get("needs_decision") or brief.get("requires_human") is True:
        reasons.append("Operator decision required")
    if t.get("live") or t.get("executing") or t.get("stage") in ("active", "progress", "doing"):
        reasons.append("Already active or executing")
    if t.get("stage") in ("blocked", "done", "review", "show_tell"):
        reasons.append("Source stage requires reconciliation or review")
    if readiness.get("stale"):
        reasons.append("Readiness assessment is stale")
    verdict = str(readiness.get("verdict") or "UNKNOWN")
    if verdict.upper() != "READY":
        reasons.append("Readiness: " + verdict[:128])
    if readiness.get("verified") is not True:
        reasons.append("Readiness is not verified")
    if "not authorized for autonomous execution" in str(excerpt).lower():
        reasons.append("Explicit execution denial in source excerpt")
    return reasons


def project_payload(payload: dict[str, Any], origin: str, state: str, offset: int, now: float | None = None) -> dict[str, Any]:
    require_complete(payload)
    generated = payload.get("generated_at")
    stale, _age, observed = freshness(payload, now)
    rows: list[dict[str, Any]] = []
    for t in payload["tickets"]:
        if not isinstance(t, dict) or t.get("kind") != "work":
            continue
        key = t.get("key")
        if not isinstance(key, str) or len(key) > 128:
            continue
        readiness = t.get("readiness") if isinstance(t.get("readiness"), dict) else {}
        reasons = execution_holds(t, stale, str(t.get("detail_head") or ""))
        reasons.extend(["Source claim and access grant not acquired", "Full context, dependencies, acceptance checks and tool entitlement not verified"])
        rows.append({
            "key": key,
            "title": str(t.get("title") or "")[:500],
            "project": str(t.get("project") or "Unassigned")[:200],
            "stage": str(t.get("stage") or "unknown")[:64],
            "priority": t.get("priority") if type(t.get("priority")) is int else None,
            "owner": str(t.get("owner") or "")[:200],
            "tags": tag_list(t.get("tags")),
            "readiness": str(readiness.get("verdict") or "UNKNOWN")[:128],
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


def project_session_context(envelope: Any) -> dict[str, Any]:
    """Minimize one Taskrivet context envelope for a dashboard reader.

    This is a projection only: it accepts no authority claims and never reads
    terminal output, ticket detail beyond the bounded envelope, or credentials.
    """
    if not isinstance(envelope, dict) or envelope.get("schema") != CONTEXT_SCHEMA:
        raise ValueError("Unsupported Taskrivet context envelope")
    ticket = envelope.get("ticket") if isinstance(envelope.get("ticket"), dict) else {}
    task = envelope.get("task") if isinstance(envelope.get("task"), dict) else {}
    session = envelope.get("session") if isinstance(envelope.get("session"), dict) else {}
    provenance = envelope.get("provenance") if isinstance(envelope.get("provenance"), dict) else {}
    binding = session.get("binding") if session.get("binding") in ("owner", "joined", "standalone") else "standalone"
    return {
        "adapter": "taskrivet-session-context",
        "schema": CONTEXT_SCHEMA,
        "ticket": {"key": ticket.get("key"), "title": str(ticket.get("title") or "")[:500]},
        "task": {"id": task.get("id"), "objective": str(task.get("objective") or "")[:1000],
                 "acceptance": str(task.get("acceptance") or "")[:1000]},
        "session": {"id": session.get("id"), "status": session.get("status"),
                    "binding": binding, "shared_count": session.get("shared_count")
                    if type(session.get("shared_count")) is int and session.get("shared_count") >= 0 else 0},
        "authority": {"context_readonly": True, "ticket_mutation": False,
                      "acceptance": False, "execution_authorized": False},
        "provenance": {"source": str(provenance.get("source") or "Taskrivet")[:200],
                       "generated_at": provenance.get("generated_at")},
        "dispatch_enabled": False,
    }


def preview(base: str, state: str = "planned", offset: int = 0) -> dict[str, Any]:
    url = endpoint(base, state, offset)
    return project_payload(fetch_json(url, timeout=10), base, state, offset)
