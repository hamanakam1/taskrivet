"""Synthetic owner protocol and crash-boundary tests; no provider is executed."""
from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit
import uuid

from synthetic import FakeTicketService, ticket
from taskrivet import config, execution as ex
from taskrivet.core import Ledger
from taskrivet.loop import import_snapshot
from taskrivet.tickets import get_ticket

REPO = Path(__file__).resolve().parents[1]


class SyntheticOwner(FakeTicketService):
    def __init__(self):
        self.records = {}
        self.posts = []
        self.owner_status = 200
        self.drop_reply = False
        self.drop_before_commit = False
        self.receipt_change = None
        self.post_status = None
        super().__init__([ticket("M-1")])
        self.preflight = {
            "schema_version": ex.SCHEMA, "kind": "preflight", "item": 1,
            "source": {"origin": self.origin, "ticket_key": "M-1"},
            "card_revision": "a" * 64, "control_revision": "b" * 64, "route_revision": "c" * 64,
            "route_policy": dict(ex.POLICY),
            "route": {"model": "synthetic-local:1", "engine": "strict-local", "cost_class": "zero_incremental",
                      "configured": True, "qualified": False, "qualification": "validated_on_call"},
            "requestable": True, "reason_codes": [],
            "evidence": {"ready": True, "verified": True, "fresh": True, "authorization": "existing_receipt"},
            "source_acceptance_required": True, "execution_authorized": False,
        }

    def error(self, code):
        return {"schema_version": ex.SCHEMA, "kind": "error", "error": code}

    def _handler(self):
        base = super()._handler()
        service = self

        class Handler(base):
            def do_GET(self):
                path = urlsplit(self.path).path
                if not path.startswith("/execution/"):
                    return super().do_GET()
                service.requests.append(("GET", path, {}))
                if service.owner_status != 200:
                    return self.reply(service.owner_status, service.error("owner_unavailable"))
                if path == "/execution/preflight":
                    return self.reply(200, service.preflight)
                if path.startswith("/execution/requests/"):
                    row = service.records.get(path.rsplit("/", 1)[-1])
                    if row is None:
                        return self.reply(404, service.error("request_not_found"))
                    row = copy.deepcopy(row)
                    if service.receipt_change:
                        service.receipt_change(row)
                    return self.reply(200, row)
                return self.reply(404, service.error("not_found"))

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                service.posts.append(data)
                service.requests.append(("POST", self.path, {}))
                if service.post_status:
                    return self.reply(service.post_status, service.error("stale_card_revision"))
                rid = data["request_id"]
                if rid in service.records:
                    old = service.records[rid]
                    if ex.canonical(old["request"]) != ex.canonical(data):
                        return self.reply(409, service.error("request_id_conflict"))
                    return self.reply(200, dict(old, replayed=True))
                row = {"schema_version": ex.SCHEMA, "kind": "request", "request": data,
                       "request_digest": ex.digest(data), "status": "requested", "reason_codes": [],
                       "owner_result": None, "run_id": str(uuid.uuid4()), "replayed": False,
                       "execution_authorized": False, "source_acceptance_required": True}
                if not service.drop_before_commit:
                    service.records[rid] = row
                if service.drop_reply or service.drop_before_commit:
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                return self.reply(202, row)

        return Handler


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.owner = SyntheticOwner()
        self.db = self.root / "ledger.sqlite"
        ledger = Ledger(self.db)
        try:
            self.task = import_snapshot(ledger, get_ticket(self.owner.origin, "M-1"))["task_id"]
        finally:
            ledger.close()
        self.cfg = {"execution": {"bindings": [{"source_origin": self.owner.origin,
                                                 "owner_origin": self.owner.origin}], "timeout": 1}}
        self.path = self.root / "execution.sqlite"
        self.journal = ex.Journal(self.path)

    def tearDown(self):
        self.journal.close()
        self.owner.close()
        self.temp.cleanup()

    def prepare(self, rid=None):
        return ex.prepare(self.db, self.task, self.cfg, self.journal, rid)

    def test_preflight_is_get_only_and_keeps_eligibility_distinct(self):
        view = ex.preflight(self.db, self.task, self.cfg)
        self.assertEqual(view["status"], "requestable")
        self.assertFalse(view["execution_authorized"])
        self.assertFalse(view["preflight"]["route"]["qualified"])
        self.assertEqual(view["preflight"]["route"]["qualification"], "validated_on_call")
        self.assertEqual(self.owner.posts, [])
        self.assertNotIn("evidence", view["preflight"])

    def test_intent_is_durable_private_and_preparing_again_is_same_request(self):
        prepared = self.prepare()
        self.assertEqual(prepared["status"], "prepared")
        self.assertTrue(prepared["can_submit"])
        self.assertEqual(prepared["send_count"], 0)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        other = ex.Journal(self.path)
        try:
            self.assertEqual(ex.inspect(other, prepared["request_id"])["request"], prepared["request"])
        finally:
            other.close()
        self.assertEqual(self.prepare()["request_id"], prepared["request_id"])
        self.assertNotIn("Synthetic task", self.path.read_bytes().decode(errors="ignore"))
        self.assertEqual(self.owner.posts, [])

    def test_same_request_id_conflicting_payload_is_refused_before_post(self):
        first = self.prepare("synthetic-request-01")
        self.assertEqual(self.prepare("synthetic-request-01")["request"], first["request"])
        self.owner.preflight["control_revision"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "conflicts"):
            self.prepare("synthetic-request-01")
        self.assertEqual(self.owner.posts, [])

    def test_duplicate_intent_with_another_id_is_not_a_second_attempt(self):
        self.prepare("synthetic-request-01")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.prepare("synthetic-request-02")

    def test_lost_ack_after_owner_commit_reads_exact_receipt_without_replay(self):
        prepared = self.prepare()
        self.owner.drop_reply = True
        result = ex.submit(self.db, self.journal, prepared["request_id"], self.cfg)
        self.assertEqual(result["status"], "requested")
        self.assertEqual(result["receipt"]["request"], prepared["request"])
        self.assertEqual(result["send_count"], 1)
        again = ex.submit(self.db, self.journal, prepared["request_id"], self.cfg)
        self.assertEqual(again["status"], "requested")
        self.assertEqual(len(self.owner.posts), 1)

    def test_missing_receipt_after_unknown_ack_never_allows_post_retry(self):
        prepared = self.prepare()
        self.owner.drop_before_commit = True
        result = ex.submit(self.db, self.journal, prepared["request_id"], self.cfg)
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertIn("submission_acknowledgement_unknown", result["reason_codes"])
        self.assertIn("owner_receipt_absent_not_replayable", result["reason_codes"])
        self.journal.close()
        self.journal = ex.Journal(self.path)
        self.owner.drop_before_commit = False
        self.assertFalse(ex.submit(self.db, self.journal, prepared["request_id"], self.cfg)["can_submit"])
        self.assertEqual(len(self.owner.posts), 1)

    def test_crash_between_intent_commit_and_network_requires_reconciliation(self):
        prepared = self.prepare()
        self.assertTrue(self.journal.begin_send(prepared["request_id"]))
        self.journal.close()
        self.journal = ex.Journal(self.path)
        result = ex.submit(self.db, self.journal, prepared["request_id"], self.cfg)
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertEqual(self.owner.posts, [])

    def test_concurrent_submit_processes_share_one_durable_send(self):
        rid = self.prepare()["request_id"]

        def run():
            journal = ex.Journal(self.path)
            try:
                return ex.submit(self.db, journal, rid, self.cfg)
            finally:
                journal.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(len(self.owner.posts), 1)
        self.assertTrue(all(result["send_count"] == 1 for result in results))
        self.assertEqual(ex.reconcile(self.journal, rid, self.cfg)["status"], "requested")

    def test_each_revision_change_holds_prepared_intent_without_rebinding(self):
        for key in ("card_revision", "control_revision", "route_revision"):
            with self.subTest(revision=key):
                original = self.owner.preflight[key]
                rid = self.prepare()["request_id"]
                self.owner.preflight[key] = "d" * 64
                result = ex.submit(self.db, self.journal, rid, self.cfg)
                self.assertEqual(result["status"], "held")
                self.assertIn("owner_revision_changed", result["reason_codes"])
                self.owner.preflight[key] = original
                # A hold does not magically become a new sendable intent.
                self.assertFalse(ex.submit(self.db, self.journal, rid, self.cfg)["can_submit"])
                self.owner.preflight["card_revision"] = ex.digest(key)
        self.assertEqual(self.owner.posts, [])

    def test_original_source_mapping_cannot_be_overridden_by_ticket_default(self):
        self.cfg["ticket_service"] = {"origin": "http://127.0.0.1:9"}
        self.assertEqual(ex.preflight(self.db, self.task, self.cfg)["binding"]["source_origin"], self.owner.origin)
        rid = self.prepare()["request_id"]
        self.cfg["execution"]["bindings"][0]["owner_origin"] = "http://127.0.0.1:9"
        result = ex.submit(self.db, self.journal, rid, self.cfg)
        self.assertEqual(result["status"], "held")
        self.assertIn("source_binding_changed", result["reason_codes"])
        self.assertEqual(self.owner.posts, [])

    def test_missing_mapping_never_guesses_owner_or_contacts_source(self):
        self.owner.requests.clear()
        with self.assertRaisesRegex(ValueError, "explicitly bound"):
            ex.preflight(self.db, self.task, {})
        self.assertEqual(self.owner.requests, [])

    def test_wrong_source_identity_and_boolean_item_fail_closed(self):
        for field, value in (("source", {"origin": "http://127.0.0.1:9", "ticket_key": "M-1"}),
                             ("source", {"origin": self.owner.origin, "ticket_key": "M-2"}), ("item", True)):
            old = self.owner.preflight[field]
            self.owner.preflight[field] = value
            result = ex.preflight(self.db, self.task, self.cfg)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["reason_codes"], ["owner_source_identity_mismatch"])
            self.owner.preflight[field] = old

    def test_policy_and_declared_qualification_do_not_open_paid_or_unknown_route(self):
        original = copy.deepcopy(self.owner.preflight)
        changes = [lambda p: p["route_policy"].update(allow_paid=True),
                   lambda p: p["route_policy"].update(allow_unknown_entitlement=True),
                   lambda p: p["route_policy"].update(allow_paid=0),
                   lambda p: p["route"].update(cost_class="paid"),
                   lambda p: p["route"].update(cost_class="unknown"),
                   lambda p: p["route"].update(qualified=True),
                   lambda p: p["route"].update(engine="cloud")]
        for change in changes:
            self.owner.preflight = copy.deepcopy(original)
            change(self.owner.preflight)
            self.assertEqual(ex.preflight(self.db, self.task, self.cfg)["status"], "unavailable")
        self.assertEqual(self.owner.posts, [])

    def test_owner_holds_and_unconfigured_route_are_preserved_without_post(self):
        self.owner.preflight.update(requestable=False, reason_codes=["pause", "strict_local_route_unconfigured"])
        self.owner.preflight["route"] = {"model": None, "engine": None, "cost_class": "unknown",
                                         "configured": False, "qualified": False, "qualification": "unavailable"}
        result = self.prepare()
        self.assertEqual(result["status"], "held")
        self.assertEqual(result["reason_codes"], ["pause", "strict_local_route_unconfigured"])
        self.assertEqual(ex.submit(self.db, self.journal, result["request_id"], self.cfg)["status"], "held")
        self.assertEqual(self.owner.posts, [])

    def test_ticket_definition_changes_and_no_auto_are_not_acknowledged_by_client(self):
        rid = self.prepare()["request_id"]
        self.owner.tickets["M-1"].update(detail="Synthetic changed objective", tags=["no-auto"])
        result = ex.submit(self.db, self.journal, rid, self.cfg)
        self.assertEqual(result["status"], "held")
        self.assertIn("imported_ticket_revision_changed", result["reason_codes"])
        self.assertIn("ticket_source_holds", result["reason_codes"])
        self.assertEqual(self.owner.posts, [])

    def test_wrong_receipt_identity_or_revision_never_confirms_unknown_write(self):
        for key, value in (("request_id", "different-request"), ("item", 2),
                           ("expected_card_revision", "d" * 64), ("route_policy", {"allow_paid": True})):
            with self.subTest(key=key):
                self.owner.preflight["card_revision"] = ex.digest(key)
                rid = self.prepare()["request_id"]
                self.owner.drop_reply = True

                def change(row):
                    row["request"][key] = value
                    row["request_digest"] = ex.digest(row["request"])

                self.owner.receipt_change = change
                result = ex.submit(self.db, self.journal, rid, self.cfg)
                self.assertEqual(result["status"], "outcome_unknown")
                self.assertIsNone(result["receipt"])
                self.assertFalse(result["can_submit"])
        self.assertEqual(len(self.owner.posts), 4)

    def test_http_conflict_is_recorded_then_reconciled_without_retry(self):
        rid = self.prepare()["request_id"]
        self.owner.post_status = 409
        result = ex.submit(self.db, self.journal, rid, self.cfg)
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertIn("stale_card_revision", result["reason_codes"])
        self.owner.post_status = None
        ex.submit(self.db, self.journal, rid, self.cfg)
        self.assertEqual(len(self.owner.posts), 1)

    def test_unavailable_owner_is_not_an_empty_receipt_or_permission(self):
        rid = self.prepare()["request_id"]
        self.owner.owner_status = 503
        result = ex.submit(self.db, self.journal, rid, self.cfg)
        self.assertEqual(result["status"], "held")
        self.assertIn("owner_unavailable", result["reason_codes"])
        self.assertEqual(self.owner.posts, [])

    def test_explicit_prepare_can_recheck_unsent_hold_but_never_an_unknown_send(self):
        rid = self.prepare()["request_id"]
        self.owner.owner_status = 503
        ex.submit(self.db, self.journal, rid, self.cfg)
        self.owner.owner_status = 200
        prepared = self.prepare()
        self.assertEqual(prepared["request_id"], rid)
        self.assertEqual(prepared["status"], "prepared")
        self.owner.drop_before_commit = True
        ex.submit(self.db, self.journal, rid, self.cfg)
        self.assertEqual(self.prepare()["status"], "outcome_unknown")
        self.assertEqual(len(self.owner.posts), 1)

    def test_owner_result_must_belong_to_the_preallocated_run(self):
        rid = self.prepare()["request_id"]
        ex.submit(self.db, self.journal, rid, self.cfg)
        row = self.owner.records[rid]
        row.update(status="owner_returned", owner_result={"run_id": str(uuid.uuid4()), "result": "show_tell"})
        result = ex.reconcile(self.journal, rid, self.cfg)
        self.assertEqual(result["status"], "requested")
        self.assertIn("owner_receipt_unavailable_or_invalid", result["reason_codes"])
        self.assertIsNone(result["receipt"]["owner_result"])

    def test_missing_run_identity_cannot_confirm_an_uncertain_request(self):
        rid = self.prepare()["request_id"]
        self.owner.drop_reply = True
        self.owner.receipt_change = lambda row: row.update(run_id=None)
        result = ex.submit(self.db, self.journal, rid, self.cfg)
        self.assertEqual(result["status"], "outcome_unknown")
        self.assertIsNone(result["receipt"])

    def test_run_identity_cannot_change_during_nonterminal_reconciliation(self):
        rid = self.prepare()["request_id"]
        initial = ex.submit(self.db, self.journal, rid, self.cfg)
        original = initial["receipt"]["run_id"]
        self.owner.records[rid].update(status="submitting", run_id=str(uuid.uuid4()))
        result = ex.reconcile(self.journal, rid, self.cfg)
        self.assertEqual(result["status"], "requested")
        self.assertEqual(result["receipt"]["run_id"], original)
        self.assertIn("owner_receipt_unavailable_or_invalid", result["reason_codes"])
        self.assertEqual(len(self.owner.posts), 1)

    def test_stale_poll_or_outage_cannot_erase_observed_terminal_owner_state(self):
        rid = self.prepare()["request_id"]
        ex.submit(self.db, self.journal, rid, self.cfg)
        row = self.owner.records[rid]
        row.update(status="owner_returned", owner_result={"run_id": row["run_id"], "result": "blocked"})
        ex.reconcile(self.journal, rid, self.cfg)
        row.update(status="requested", owner_result=None)
        self.assertEqual(ex.reconcile(self.journal, rid, self.cfg)["status"], "owner_returned")
        self.owner.owner_status = 503
        self.assertEqual(ex.reconcile(self.journal, rid, self.cfg)["status"], "owner_returned")
        self.assertEqual(len(self.owner.posts), 1)

    def test_observation_only_reads_existing_request_and_stops_on_owner_return(self):
        rid = self.prepare()["request_id"]
        ex.observe(self.journal, rid, self.cfg, count=2, interval=0.1)
        self.assertEqual(self.owner.posts, [])
        ex.submit(self.db, self.journal, rid, self.cfg)
        row = self.owner.records[rid]
        row.update(status="owner_returned", owner_result={"run_id": row["run_id"], "result": "show_tell"})
        result = ex.observe(self.journal, rid, self.cfg, count=5, interval=0.1)
        self.assertEqual(result["polls"], 1)
        self.assertEqual(result["status"], "owner_returned")
        self.assertTrue(result["source_acceptance_required"])
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["admitted_additional_tickets"])
        self.assertEqual(len(self.owner.posts), 1)

    def test_inspection_is_offline_and_unsafe_journal_files_are_refused(self):
        rid = self.prepare()["request_id"]
        count = len(self.owner.requests)
        self.assertEqual(ex.inspect(self.journal, rid)["status"], "prepared")
        self.assertEqual(len(self.owner.requests), count)
        link = self.root / "linked.sqlite"
        link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "private regular"):
            ex.Journal(link)
        self.path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "private regular"):
            ex.Journal(self.path)
        self.path.chmod(0o600)

    def test_config_rejects_remote_ambiguous_or_spend_override_settings(self):
        for change in ({"bindings": [{"source_origin": self.owner.origin, "owner_origin": "https://example.com"}]},
                       {"bindings": self.cfg["execution"]["bindings"] * 2}, {"allow_paid": True},
                       {"timeout": 31}, {"timeout": True}, {"journal_path": "relative.sqlite"}):
            with self.assertRaises(ValueError):
                config.validate({"execution": change})

    def test_cli_prepares_inspects_and_observes_without_launch_or_write(self):
        cfg = dict(self.cfg)
        cfg["execution"] = dict(cfg["execution"], journal_path=str(self.path))
        path = self.root / "config.json"
        config.save(cfg, path)
        env = {k: v for k, v in os.environ.items() if not k.startswith("TASKRIVET_")}
        env.update(TASKRIVET_CONFIG=str(path), TASKRIVET_DB=str(self.db), HOME=str(self.root), PYTHONPATH=str(REPO))

        def cli(*args):
            done = subprocess.run([sys.executable, "-m", "taskrivet", *args], cwd=REPO, env=env,
                                  capture_output=True, text=True, timeout=10)
            self.assertEqual(done.returncode, 0, done.stderr)
            return done.stdout

        self.assertEqual(json.loads(cli("execution-preflight", self.task))["status"], "requestable")
        rid = json.loads(cli("execution-prepare", self.task))["request_id"]
        self.assertEqual(json.loads(cli("execution-inspect", rid))["status"], "prepared")
        self.assertIn("Unknown outcomes are never replayed", cli("execution-inspect", rid, "--format", "table"))
        self.assertFalse(json.loads(cli("execution-observe", rid, "--count", "1"))["admitted_additional_tickets"])
        self.assertEqual(self.owner.posts, [])
        self.assertFalse((self.root / ".taskrivet" / "sessions").exists())


if __name__ == "__main__":
    unittest.main()
