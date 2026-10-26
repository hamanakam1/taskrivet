"""Read-only ticket routing observations from the optional engines protocol.

Inventory and an engine accepting connections do not qualify a model for a
ticket. This adapter exposes those observations and the missing evidence; it
never executes a model, imports a task, or treats a route as authorization.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import math
import re
import time
from typing import Any

from . import config as settings
from .dashboard import fetch_json
from .tickets import check_key, get_ticket

SCHEMA = "taskrivet.route.v1"
MAX_AGE = 300
MAX_ROUTES = 512
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")


def _timestamp(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        stamp = parsed.timestamp()
        return stamp if math.isfinite(stamp) else None
    except (ValueError, OverflowError):
        return None


def _fresh(stamp: float | None, now: float) -> bool:
    return stamp is not None and -60 <= now - stamp <= MAX_AGE


def _inventory(payload: Any) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ValueError("Unsupported engines response")
    if any(payload.get(k) for k in ("error", "errors", "refresh_error", "loading")):
        raise ValueError("Engine source reported incomplete data")
    routing = payload.get("routing")
    if not isinstance(routing, dict):
        raise ValueError("Engine source has no routing inventory")
    inventory = routing.get("inventory")
    if not isinstance(inventory, dict) or inventory.get("ready") is not True:
        raise ValueError("Model inventory is unavailable or unverified")
    routes, engines = routing.get("routes"), payload.get("engines")
    if not isinstance(routes, list) or len(routes) > MAX_ROUTES or not isinstance(engines, list):
        raise ValueError("Unsupported or oversized routing inventory")
    by_id = {}
    for engine in engines:
        if (not isinstance(engine, dict) or not isinstance(engine.get("id"), str)
                or not IDENTIFIER.fullmatch(engine["id"]) or engine["id"] in by_id):
            raise ValueError("Engine inventory has invalid or duplicate identities")
        by_id[engine["id"]] = engine
    identities = set()
    for route in routes:
        if not isinstance(route, dict) or any(
            not isinstance(route.get(k), str) or not IDENTIFIER.fullmatch(route[k])
            for k in ("model", "engine")
        ):
            raise ValueError("Model inventory has invalid route identities")
        identity = (route["engine"], route["model"])
        if identity in identities:
            raise ValueError("Model inventory has duplicate route identities")
        identities.add(identity)
    return routes, by_id


def project(snap: dict[str, Any], payload: Any, *, source: str, now: float) -> dict[str, Any]:
    """Minimize one engines observation, retaining explicit qualification gaps."""
    routes, engines = _inventory(payload)
    generated = _timestamp(payload.get("generated_at"))
    current = _fresh(generated, now) and payload.get("stale", False) is False
    holds = list(snap["holds"])
    if not snap.get("acceptance"):
        holds.append("Ticket acceptance criteria are not stated")
    if not current:
        holds.append("Engine observations are stale or their timestamp is unknown")
    candidates = []
    for route in routes:
        model, provider = route["model"], route["engine"]
        engine = engines.get(provider)
        reasons = []
        if not current:
            reasons.append("Current engine observations are required")
        if route.get("inert") is not False:
            reasons.append("Route is disabled or its enabled state is unknown")
        if route.get("local") is True:
            reasons.append("Source declares local inference; cost and tool entitlement are not verified")
        else:
            reasons.append("Provider cost and entitlement are unknown; paid fallback is not eligible")
        if engine is None:
            reasons.append("No engine health observation is linked to this route")
        else:
            if engine.get("state") != "serving" or engine.get("listening") is not True:
                reasons.append("Engine is not observed serving and listening")
            else:
                reasons.append("Engine accepts connections; this does not prove model readiness")
            probe = engine.get("probe")
            if not isinstance(probe, dict) or not probe:
                reasons.append("No completion probe observation is available")
            else:
                if not _fresh(_timestamp(probe.get("at")), now):
                    reasons.append("Completion probe is stale or its timestamp is unknown")
                if probe.get("ok") is not True:
                    reasons.append("Completion probe did not report success")
                reasons.append("Engine probe does not qualify this model for the ticket")
        reasons += [
            "No qualified local launcher is bound to this provider and model",
            "Ticket context capacity and accepted-outcome quality are not verified",
        ]
        identity = hashlib.sha256((provider + "\0" + model).encode()).hexdigest()[:24]
        candidates.append({
            "id": identity, "tool": "unbound", "provider": provider, "model": model,
            "cost_class": "unknown", "eligible": False, "reasons": reasons, "rank": None,
        })
    return {
        "schema": SCHEMA, "ticket": {"key": snap["key"], "revision": snap["revision"]},
        "status": "held", "observed_at": now, "source_current": current,
        "expires_at": min(now + MAX_AGE, generated + MAX_AGE) if current else None,
        "selected": None, "candidates": candidates, "holds": holds,
        "reasons": [
            "Route inventory is an observation, not a measured model recommendation",
            "No route has verified model capability, cost entitlement, and a local launcher binding",
            "Source claim and access grant have not been acquired",
        ] + ([] if candidates else ["No model routes were observed"]),
        "source": source, "execution_authorized": False,
    }


def ticket_route(key: str, *, cfg: dict[str, Any], origin: str | None = None,
                 now: float | None = None) -> dict[str, Any]:
    """Read a ticket and engine inventory; never open a ledger or call a provider."""
    check_key(key)
    base = settings.ticket_origin(cfg, origin)
    timeout = min(15, settings.ticket_timeout(cfg))
    observed = time.time() if now is None else now
    source = base + "/api/engines"
    result = {
        "schema": SCHEMA, "ticket": {"key": key, "revision": ""}, "status": "unavailable",
        "observed_at": observed, "source_current": False,
        "expires_at": None, "selected": None, "candidates": [],
        "holds": [], "reasons": [], "source": source, "execution_authorized": False,
    }
    try:
        snap = get_ticket(base, key, timeout=timeout, now=observed)
    except (ValueError, OSError) as exc:
        return result | {"reasons": ["Ticket read unavailable: " + str(exc)[:300]]}
    result["ticket"] = {"key": snap["key"], "revision": snap["revision"]}
    result["holds"] = snap["holds"]
    try:
        payload = fetch_json(source, timeout=timeout)
        return project(snap, payload, source=source, now=observed)
    except (ValueError, OSError) as exc:
        return result | {"reasons": ["Routing observations unavailable: " + str(exc)[:300]]}
