"""One-request source-owner transport with durable, fail-closed reconciliation.

This module never launches a process, selects another ticket, grants approval, or
marks work accepted. Only an explicit submit may POST, at most once per intent.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
import uuid

from . import config
from .core import Ledger
from .dashboard import NoRedirect, local_origin
from .tickets import get_ticket

SCHEMA = "taskrivet-execution-v1"
CLIENT_SCHEMA = "taskrivet.execution-client.v1"
POLICY = {"allow_paid": False, "allow_unknown_entitlement": False}
REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,80}\Z")
REVISION = re.compile(r"[0-9a-f]{64}\Z")
CODE = re.compile(r"[a-z][a-z0-9_]{0,127}\Z")
TICKET = re.compile(r"M-([1-9][0-9]{0,17})\Z")
OWNER_STATES = {"held", "requested", "submitting", "owner_returned", "outcome_unknown"}
RESULTS = {"refused", "lease_conflict", "blocked", "show_tell", "yielded"}
MAX_BYTES = 128 * 1024


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _codes(value: Any) -> list[str]:
    if (not isinstance(value, list) or len(value) > 64
            or any(not isinstance(x, str) or not CODE.fullmatch(x) for x in value)):
        raise ValueError("Owner returned invalid reason codes")
    return list(dict.fromkeys(value))


def _text(value: Any, limit: int = 200) -> str:
    if not isinstance(value, str) or not value or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ValueError("Owner returned invalid bounded text")
    return value


def _base(value: Any, kind: str) -> dict[str, Any]:
    if (not isinstance(value, dict) or value.get("schema_version") != SCHEMA
            or value.get("kind") != kind or value.get("execution_authorized") is not False
            or value.get("source_acceptance_required") is not True):
        raise ValueError("Owner returned an unsupported execution envelope")
    return value


class OwnerUnavailable(OSError):
    """No trustworthy acknowledgement; absence never authorizes replay."""


class ProtocolError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def exchange(origin: str, path: str, *, payload: dict[str, Any] | None = None,
             timeout: float = 10) -> tuple[int, Any]:
    """Bounded loopback JSON, no redirects, proxies, credentials, or retry."""
    origin = local_origin(origin)
    opener = build_opener(ProxyHandler({}), NoRedirect())
    headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        body = canonical(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(origin + path, data=body, headers=headers)
    try:
        try:
            response = opener.open(request, timeout=timeout)
        except HTTPError as exc:
            response = exc
        with response:
            status = response.code
            data = response.read(MAX_BYTES + 1)
    except (URLError, TimeoutError, ConnectionError, HTTPException, OSError, ValueError):
        raise OwnerUnavailable("Owner response unavailable; reconcile this exact request") from None
    if len(data) > MAX_BYTES:
        raise ValueError("Owner response exceeds the size limit")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate owner JSON field")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("Non-finite owner JSON number")

    try:
        return status, json.loads(data, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (ValueError, UnicodeError):
        raise ValueError("Owner returned invalid JSON") from None


def _error(status: int, value: Any) -> str:
    # Never copy arbitrary remote error text, paths, or executor output.
    if (isinstance(value, dict) and value.get("schema_version") == SCHEMA
            and value.get("kind") == "error" and isinstance(value.get("error"), str)
            and CODE.fullmatch(value["error"])):
        return value["error"]
    return "owner_http_" + str(status)


def binding(db: str | Path, task_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    config.validate(cfg)
    if not Path(db).expanduser().is_file():
        raise ValueError("Import a ticket before preparing owner execution")
    ledger = Ledger(db)
    try:
        source = ledger.task_source(task_id)
    finally:
        ledger.close()
    if not source:
        raise ValueError("Task has no imported ticket source")
    origin = local_origin(source["origin"])
    match = TICKET.fullmatch(source["ticket_key"])
    if not match:
        raise ValueError("This owner protocol requires a canonical numeric M- ticket key")
    owner = next((row["owner_origin"] for row in cfg.get("execution", {}).get("bindings", [])
                  if local_origin(row["source_origin"]) == origin), None)
    if owner is None:
        raise ValueError("No execution owner explicitly bound to this imported source origin")
    return {"task_id": task_id, "source_origin": origin, "owner_origin": local_origin(owner),
            "ticket_key": source["ticket_key"], "source_revision": source["revision"], "item": int(match[1])}


def _preflight(raw: Any, bound: dict[str, Any]) -> dict[str, Any]:
    value = _base(raw, "preflight")
    expected_source = {"origin": bound["source_origin"], "ticket_key": bound["ticket_key"]}
    if (type(value.get("item")) is not int or value["item"] != bound["item"]
            or canonical(value.get("source")) != canonical(expected_source)):
        raise ProtocolError("owner_source_identity_mismatch")
    if canonical(value.get("route_policy")) != canonical(POLICY):
        raise ProtocolError("owner_cost_policy_mismatch")
    if type(value.get("requestable")) is not bool:
        raise ValueError("Owner preflight has no explicit requestability")
    revisions = {}
    for key in ("card_revision", "control_revision", "route_revision"):
        rev = value.get(key)
        if rev is not None and (not isinstance(rev, str) or not REVISION.fullmatch(rev)):
            raise ValueError("Owner returned an invalid revision")
        revisions[key] = rev
    route = value.get("route")
    if (not isinstance(route, dict) or type(route.get("qualified")) is not bool
            or type(route.get("configured")) is not bool):
        raise ValueError("Owner returned an invalid route")
    route = {"model": _text(route["model"]) if route.get("model") is not None else None,
             "engine": _text(route["engine"]) if route.get("engine") is not None else None,
             "cost_class": _text(route.get("cost_class"), 64), "qualified": route["qualified"],
             "configured": route["configured"], "qualification": _text(route.get("qualification"), 64)}
    reasons = _codes(value.get("reason_codes"))
    requestable = value["requestable"]
    if requestable and (reasons or not all(revisions.values()) or not route["model"]
                        or route["configured"] is not True or route["qualified"] is not False
                        or route["qualification"] != "validated_on_call" or route["engine"] != "strict-local"
                        or route["cost_class"] != "zero_incremental"):
        raise ValueError("Owner preflight contradicts its qualification or cost constraints")
    return {"schema_version": SCHEMA, "kind": "preflight", "item": value["item"],
            "source": expected_source, **revisions, "route_policy": dict(POLICY),
            "requestable": requestable, "reason_codes": reasons, "route": route,
            "execution_authorized": False, "source_acceptance_required": True}


def preflight(db: str | Path, task_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    bound = binding(db, task_id, cfg)
    reasons = []
    try:
        ticket = get_ticket(bound["source_origin"], bound["ticket_key"], timeout=_timeout(cfg))
        if ticket["key"] != bound["ticket_key"] or ticket["revision"] != bound["source_revision"]:
            reasons.append("imported_ticket_revision_changed")
        if ticket["holds"]:
            reasons.append("ticket_source_holds")
        status, raw = exchange(bound["owner_origin"], f"/execution/preflight?item={bound['item']}",
                               timeout=_timeout(cfg))
        if status != 200:
            return {**_envelope(bound), "status": "unavailable", "reason_codes": [_error(status, raw)], "preflight": None}
        owner = _preflight(raw, bound)
    except (OSError, ValueError) as exc:
        return {**_envelope(bound), "status": "unavailable", "reason_codes": [getattr(exc, "code", "preflight_unavailable_or_invalid")], "preflight": None}
    reasons += owner["reason_codes"]
    return {**_envelope(bound), "status": "requestable" if owner["requestable"] and not reasons else "held",
            "reason_codes": list(dict.fromkeys(reasons)), "preflight": owner}


def _timeout(cfg: dict[str, Any]) -> float:
    return cfg.get("execution", {}).get("timeout", 10)


def _envelope(bound: dict[str, Any]) -> dict[str, Any]:
    return {"schema": CLIENT_SCHEMA, "binding": bound, "observed_at": time.time(),
            "execution_authorized": False, "source_acceptance_required": True}


def journal_path(db: str | Path, cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("execution", {}).get("journal_path") or (str(Path(db).expanduser()) + ".execution.sqlite")).expanduser()


class Journal:
    """Private durable intents; an uncertain attempt permanently consumes its send."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        config.private_directory(self.path.parent)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            st = self.path.lstat()
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
                raise ValueError("Execution journal must be a private regular file owned by you") from None
        else:
            os.close(fd)
        self.conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS execution_intents (
            request_id TEXT PRIMARY KEY, identity_digest TEXT NOT NULL UNIQUE,
            binding TEXT NOT NULL, request TEXT NOT NULL, request_digest TEXT NOT NULL,
            preflight TEXT NOT NULL, state TEXT NOT NULL, reasons TEXT NOT NULL,
            receipt TEXT, send_count INTEGER NOT NULL DEFAULT 0,
            created REAL NOT NULL, updated REAL NOT NULL)""")

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def get(self, request_id: str) -> dict[str, Any]:
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            raise ValueError("Invalid execution request ID")
        row = self.conn.execute("SELECT * FROM execution_intents WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            raise ValueError("Execution request is not in this local journal")
        value = dict(row)
        for key in ("binding", "request", "preflight", "reasons", "receipt"):
            value[key] = json.loads(value[key]) if value[key] is not None else None
        return value

    def prepare(self, view: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
        owner = view.get("preflight")
        if owner is None or not all(owner.get(k) for k in ("card_revision", "control_revision", "route_revision")):
            raise ValueError("A complete owner preflight is required before preparing an intent")
        rid = request_id or str(uuid.uuid4())
        if not isinstance(rid, str) or not REQUEST_ID.fullmatch(rid):
            raise ValueError("Invalid execution request ID")
        request = {"request_id": rid, "item": owner["item"], "source": owner["source"],
                   "expected_card_revision": owner["card_revision"],
                   "expected_control_revision": owner["control_revision"],
                   "expected_route_revision": owner["route_revision"], "route_policy": dict(POLICY)}
        identity = digest({"binding": view["binding"], "request": {k: v for k, v in request.items() if k != "request_id"}})
        with self.transaction():
            existing = self.conn.execute("SELECT request_id,identity_digest FROM execution_intents WHERE request_id=? OR identity_digest=?",
                                         (rid, identity)).fetchall()
            if existing:
                if len(existing) != 1 or existing[0]["identity_digest"] != identity:
                    raise ValueError("Request ID conflicts with a different immutable intent")
                if request_id and existing[0]["request_id"] != rid:
                    raise ValueError("An intent already exists for this exact source and revisions")
                rid = existing[0]["request_id"]
                # Explicit preparation can re-review an unsent hold. A sent or
                # uncertain intent never regains its send, even after a 404.
                if view["status"] == "requestable":
                    self.conn.execute("UPDATE execution_intents SET state='prepared',reasons='[]',preflight=?,updated=? WHERE request_id=? AND state='held' AND send_count=0 AND receipt IS NULL",
                                      (canonical(owner), time.time(), rid))
            else:
                now = time.time()
                state = "prepared" if view["status"] == "requestable" else "held"
                self.conn.execute("""INSERT INTO execution_intents
                    (request_id,identity_digest,binding,request,request_digest,preflight,state,reasons,created,updated)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""", (rid, identity, canonical(view["binding"]), canonical(request),
                    digest(request), canonical(owner), state, canonical(view["reason_codes"]), now, now))
        return self.get(rid)

    def begin_send(self, request_id: str) -> bool:
        with self.transaction():
            result = self.conn.execute("UPDATE execution_intents SET state='submitting',send_count=1,updated=? WHERE request_id=? AND state='prepared' AND send_count=0",
                                       (time.time(), request_id))
        return result.rowcount == 1

    def note(self, request_id: str, state: str, reasons: list[str]) -> dict[str, Any]:
        with self.transaction():
            value = self.get(request_id)
            # A late unavailable poll cannot erase an already observed owner receipt.
            if value["receipt"] is not None:
                state = value["state"]
            reasons = list(dict.fromkeys(value["reasons"] + reasons))
            self.conn.execute("UPDATE execution_intents SET state=?,reasons=?,updated=? WHERE request_id=?",
                              (state, canonical(reasons), time.time(), request_id))
        return self.get(request_id)

    def receipt(self, request_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
        with self.transaction():
            old = self.get(request_id)
            if old["receipt"] and old["receipt"]["run_id"] != receipt["run_id"]:
                raise ValueError("Owner receipt changed the original run identity")
            if old["receipt"] and old["state"] in {"held", "owner_returned"} and old["state"] != receipt["status"]:
                raise ValueError("Owner receipt regressed from a terminal request state")
            self.conn.execute("UPDATE execution_intents SET state=?,reasons=?,receipt=?,updated=? WHERE request_id=?",
                              (receipt["status"], canonical(receipt["reason_codes"]), canonical(receipt), time.time(), request_id))
        return self.get(request_id)


def inspect(journal: Journal, request_id: str) -> dict[str, Any]:
    row = journal.get(request_id)
    return {**_envelope(row["binding"]), "request_id": request_id, "request": row["request"],
            "request_digest": row["request_digest"], "status": row["state"], "reason_codes": row["reasons"],
            "send_count": row["send_count"], "receipt": row["receipt"], "created_at": row["created"],
            "updated_at": row["updated"], "can_submit": row["state"] == "prepared" and row["send_count"] == 0}


def prepare(db: str | Path, task_id: str, cfg: dict[str, Any], journal: Journal,
            request_id: str | None = None) -> dict[str, Any]:
    view = preflight(db, task_id, cfg)
    row = journal.prepare(view, request_id)
    return inspect(journal, row["request_id"])


def _receipt(raw: Any, row: dict[str, Any]) -> dict[str, Any]:
    value = _base(raw, "request")
    if (canonical(value.get("request")) != canonical(row["request"])
            or value.get("request_digest") != row["request_digest"]):
        raise ValueError("Owner receipt does not match this exact request and revisions")
    if value.get("status") not in OWNER_STATES or type(value.get("replayed")) is not bool:
        raise ValueError("Owner returned an invalid request state")
    run_id = str(uuid.UUID(_text(value.get("run_id"), 36)))
    if row["receipt"] and row["receipt"]["run_id"] != run_id:
        raise ValueError("Owner receipt changed the original run identity")
    result = value.get("owner_result")
    if result is not None:
        if not isinstance(result, dict) or result.get("result") not in RESULTS:
            raise ValueError("Owner returned an invalid outcome")
        result = {"run_id": str(uuid.UUID(_text(result.get("run_id"), 36))), "result": result["result"]}
        if run_id != result["run_id"]:
            raise ValueError("Owner outcome belongs to a different run")
    if value["status"] == "owner_returned" and result is None:
        raise ValueError("Owner returned no outcome identity")
    return {"schema_version": SCHEMA, "kind": "request", "request": row["request"],
            "request_digest": row["request_digest"], "status": value["status"],
            "reason_codes": _codes(value.get("reason_codes")), "run_id": run_id,
            "owner_result": result, "replayed": value["replayed"],
            "execution_authorized": False, "source_acceptance_required": True}


def reconcile(journal: Journal, request_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    row = journal.get(request_id)
    try:
        status, raw = exchange(row["binding"]["owner_origin"], "/execution/requests/" + request_id,
                               timeout=_timeout(cfg))
        if status == 200:
            journal.receipt(request_id, _receipt(raw, row))
        else:
            state = "outcome_unknown" if row["send_count"] else row["state"]
            code = ("owner_receipt_absent_not_replayable" if row["send_count"] else "owner_receipt_not_yet_created") if status == 404 else _error(status, raw)
            journal.note(request_id, state, [code])
    except (OSError, ValueError):
        state = "outcome_unknown" if row["send_count"] else row["state"]
        journal.note(request_id, state, ["owner_receipt_unavailable_or_invalid"])
    return inspect(journal, request_id)


def submit(db: str | Path, journal: Journal, request_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    row = journal.get(request_id)
    if row["send_count"]:
        return reconcile(journal, request_id, cfg)
    if row["state"] != "prepared":
        return inspect(journal, request_id)
    try:
        view = preflight(db, row["binding"]["task_id"], cfg)
    except (OSError, ValueError):
        journal.note(request_id, "held", ["source_binding_unavailable_or_changed"])
        return inspect(journal, request_id)
    owner = view.get("preflight")
    if view["binding"] != row["binding"]:
        reasons = ["source_binding_changed"]
    elif view["status"] != "requestable":
        reasons = view["reason_codes"] or ["owner_not_requestable"]
    elif any(owner[key] != row["request"]["expected_" + key] for key in ("card_revision", "control_revision", "route_revision")):
        reasons = ["owner_revision_changed"]
    else:
        reasons = []
    if reasons:
        journal.note(request_id, "held", reasons)
        return inspect(journal, request_id)
    # FULL synchronous transaction is committed before entering transport. A crash
    # after this boundary always requires GET, even if the POST never reached owner.
    if not journal.begin_send(request_id):
        return reconcile(journal, request_id, cfg)
    try:
        status, raw = exchange(row["binding"]["owner_origin"], "/execution/requests",
                               payload=row["request"], timeout=_timeout(cfg))
        if status in (200, 201, 202):
            journal.receipt(request_id, _receipt(raw, row))
            return inspect(journal, request_id)
        journal.note(request_id, "outcome_unknown", [_error(status, raw)])
    except (OSError, ValueError):
        journal.note(request_id, "outcome_unknown", ["submission_acknowledgement_unknown"])
    # One readback now; never a retrying POST, including on HTTP conflict or 404.
    return reconcile(journal, request_id, cfg)


def observe(journal: Journal, request_id: str, cfg: dict[str, Any], *, count: int = 10,
            interval: float = 2) -> dict[str, Any]:
    if type(count) is not int or not 1 <= count <= 100:
        raise ValueError("Observation count must be 1-100")
    if type(interval) not in (int, float) or not 0.1 <= interval <= 30:
        raise ValueError("Observation interval must be 0.1-30 seconds")
    journal.get(request_id)
    result = None
    for index in range(count):
        if index:
            time.sleep(interval)
        result = reconcile(journal, request_id, cfg)
        if result["receipt"] and result["status"] in {"held", "owner_returned"}:
            break
    return {**result, "polls": index + 1, "admitted_additional_tickets": False}
