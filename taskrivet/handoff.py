"""Confirmation-gated, local-only handoff to the AI Dashboard."""
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

from .dashboard import MAX_BYTES, NoRedirect, local_origin


class HandoffUnavailable(OSError):
    """The local dashboard could not accept a bounded handoff request."""


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
