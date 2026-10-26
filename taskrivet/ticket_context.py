"""Read-only ticket/session context for dashboard integrations.

This module deliberately exposes recorded context, not authority.  Consumers
must treat the returned envelope as display and handoff metadata only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SCHEMA = "taskrivet.ticket-context.v1"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build(detail: dict[str, Any], *, ticket: dict[str, Any] | None = None,
          generated_at: str | None = None) -> dict[str, Any]:
    """Build a bounded, non-authorizing context envelope from ledger detail.

    ``detail`` is the local ledger's read-only ``Ledger.detail`` view.  Ticket
    fields are optional because a standalone local task remains useful without
    a dashboard ticket.  No caller-provided authority flags are accepted.
    """
    task = detail.get("task") if isinstance(detail.get("task"), dict) else {}
    session = detail.get("session") if isinstance(detail.get("session"), dict) else {}
    sessions = detail.get("sessions") if isinstance(detail.get("sessions"), list) else []
    ticket = ticket if isinstance(ticket, dict) else {}
    ticket_key = ticket.get("key")
    session_id = session.get("id")
    binding = "standalone"
    if ticket_key and session_id:
        binding = str(session.get("binding") or "owner")
        if binding not in {"owner", "joined"}:
            binding = "owner"
    return {
        "schema": SCHEMA,
        "ticket": {
            "key": ticket_key if isinstance(ticket_key, str) else None,
            "revision": ticket.get("revision") if isinstance(ticket.get("revision"), str) else None,
            "title": ticket.get("title") if isinstance(ticket.get("title"), str) else None,
        },
        "task": {
            "id": task.get("id"),
            "objective": task.get("objective"),
            "acceptance": task.get("acceptance"),
            "scope": task.get("scope") if isinstance(task.get("scope"), list) else [],
        },
        "session": {
            "id": session_id,
            "status": session.get("status"),
            "binding": binding,
            "shared_count": sum(1 for row in sessions if isinstance(row, dict)
                                 and row.get("status") == "active"),
        },
        "authority": {
            "context_readonly": True,
            "ticket_mutation": False,
            "acceptance": False,
            "execution_authorized": False,
        },
        "provenance": {
            "source": "taskrivet local ledger",
            "generated_at": generated_at or _iso_now(),
        },
    }
