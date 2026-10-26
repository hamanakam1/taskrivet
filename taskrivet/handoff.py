"""Confirmation-gated, local-only handoff to the AI Dashboard."""
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener
from urllib.parse import urlencode

from .dashboard import MAX_BYTES, NoRedirect, local_origin


class HandoffUnavailable(OSError):
    """The local dashboard could not accept a bounded handoff request."""


def _get_json(url: str, timeout: float, max_bytes: int) -> dict[str, Any]:
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(Request(url, headers={"Accept": "application/json"}), timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except HTTPError as exc:
        exc.close()
        raise HandoffUnavailable(f"Dashboard returned HTTP {exc.code}") from None
    except (URLError, TimeoutError, ConnectionError) as exc:
        raise HandoffUnavailable(f"Dashboard unavailable: {getattr(exc, 'reason', exc)}") from None
    if len(data) > max_bytes:
        raise ValueError(f"Dashboard response exceeds {max_bytes} bytes")
    try:
        result = json.loads(data)
    except ValueError:
        raise ValueError("Dashboard returned invalid JSON") from None
    if not isinstance(result, dict):
        raise ValueError("Dashboard returned an unsupported response")
    return result


def history(base: str, limit: int = 20, timeout: float = 10, max_bytes: int = MAX_BYTES) -> dict[str, Any]:
    """Read bounded evidence-only receipt history; never restores authority."""
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("History limit must be 1-50")
    result = _get_json(local_origin(base) + "/api/taskrivet/handoffs?" + urlencode({"limit": limit}), timeout, max_bytes)
    if result.get("ok") is not True or result.get("mode") != "evidence-only" or result.get("execution_authorized") is not False or result.get("dispatch_enabled") is not False:
        raise ValueError("Dashboard history is not evidence-only")
    rows = result.get("handoffs")
    if not isinstance(rows, list) or len(rows) > limit:
        raise ValueError("Dashboard history is malformed or unbounded")
    for row in rows:
        if not isinstance(row, dict) or row.get("evidence_only") is not True or row.get("execution_authorized") is not False:
            raise ValueError("Dashboard history contains an unsafe row")
    return result


def submit(base: str, envelope: Any, timeout: float = 10, max_bytes: int = MAX_BYTES) -> dict[str, Any]:
    """Submit context for local confirmation; never dispatches or mutates tickets."""
    origin = local_origin(base)
    if not isinstance(envelope, dict):
        raise ValueError("Handoff envelope must be a JSON object")
    body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode()
    if len(body) > max_bytes:
        raise ValueError(f"Handoff request exceeds {max_bytes} bytes")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(origin + "/api/taskrivet/handoff", data=body, method="POST",
                      headers={"Accept": "application/json", "Content-Type": "application/json"})
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
    except HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read(65536) or b"{}")
            if isinstance(payload, dict):
                detail = str(payload.get("error") or "")[:200]
        except (ValueError, OSError):
            pass
        finally:
            exc.close()
        raise HandoffUnavailable(f"Dashboard returned HTTP {exc.code}" + (": " + detail if detail else "")) from None
    except (URLError, TimeoutError, ConnectionError) as exc:
        raise HandoffUnavailable(f"Dashboard unavailable: {getattr(exc, 'reason', exc)}") from None
    if len(data) > max_bytes:
        raise ValueError(f"Dashboard response exceeds {max_bytes} bytes")
    try:
        result = json.loads(data)
    except ValueError:
        raise ValueError("Dashboard returned invalid JSON") from None
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise ValueError("Dashboard did not accept the handoff")
    if result.get("requires_local_confirmation") is not True:
        raise ValueError("Dashboard handoff is not confirmation-gated")
    if result.get("dispatch_enabled") is not False:
        raise ValueError("Dashboard handoff unexpectedly enables dispatch")
    authority = result.get("authority") if isinstance(result.get("authority"), dict) else {}
    if authority.get("context_readonly") is not True or any(authority.get(key) is not False for key in ("ticket_mutation", "acceptance", "execution_authorized")):
        raise ValueError("Dashboard handoff contains an unsafe authority claim")
    receipt = result.get("receipt")
    if not isinstance(receipt, dict) or not receipt.get("request_id") or len(str(receipt.get("context_hash") or "")) != 64:
        raise ValueError("Dashboard handoff receipt is missing or incomplete")
    return result
