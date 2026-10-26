"""Routing observations through the real local HTTP and CLI protocols."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

from synthetic import FakeTicketService, ticket
from taskrivet import config
from taskrivet.core import Ledger
from taskrivet.routing import MAX_AGE, ticket_route

NOW = 1_800_000_000.0
REPO = Path(__file__).resolve().parents[1]


def iso(stamp):
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat()


def observation():
    return {
        "generated_at": iso(NOW),
        "engines": [{"id": "local-engine", "state": "serving", "listening": True,
                     "probe": {"at": iso(NOW), "ok": True, "reply": "private probe text"},
                     "pid": 123, "path": "/private/installation"}],
        "routing": {
            "inventory": {"ready": True, "count": 2},
            "routes": [
                {"model": "example-code:small", "engine": "local-engine", "local": True, "inert": False},
                {"model": "example-cloud", "engine": "cloud", "local": False, "inert": False,
                 "key_item": "private-credential-name"},
            ],
            "executor_ladder": ["example-code:small"],
            "turns": {"recent": [{"title": "private task title", "seconds": 1}]},
        },
        "execution_authorized": True,
    }


class RoutingService(FakeTicketService):
    def __init__(self):
        self.engines = observation()
        self.engine_status = 200
        super().__init__([ticket("SYN-1"), ticket("SYN-2", tags=["no-auto"])])

    def _handler(self):
        service = self
        base = super()._handler()

        class Handler(base):
            def do_GET(self):
                if urlsplit(self.path).path == "/api/engines":
                    service.requests.append(("GET", "/api/engines", {}))
                    return self.reply(service.engine_status, service.engines)
                return super().do_GET()

        return Handler


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.svc = RoutingService()
        self.cfg = {"ticket_service": {"origin": self.svc.origin}}

    def tearDown(self):
        self.svc.close()

    def read(self, key="SYN-1"):
        return ticket_route(key, cfg=self.cfg, now=NOW)

    def test_inventory_is_minimized_and_does_not_invent_model_qualification(self):
        result = self.read()
        self.assertEqual(result["schema"], "taskrivet.route.v1")
        self.assertEqual(result["status"], "held")
        self.assertEqual(result["ticket"]["key"], "SYN-1")
        self.assertEqual(len(result["ticket"]["revision"]), 64)
        self.assertEqual(result["expires_at"], NOW + MAX_AGE)
        self.assertTrue(result["source_current"])
        self.assertIsNone(result["selected"])
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(len(result["candidates"]), 2)
        for row in result["candidates"]:
            self.assertFalse(row["eligible"])
            self.assertIsNone(row["rank"])
            self.assertEqual(row["tool"], "unbound")
            self.assertEqual(row["cost_class"], "unknown")
        encoded = json.dumps(result)
        for private in ("private probe text", "/private/installation", "private-credential-name", "private task title"):
            self.assertNotIn(private, encoded)
        self.assertEqual(self.svc.requests, [
            ("GET", "/api/tix/ticket", {"key": "SYN-1", "seen": "0"}),
            ("GET", "/api/engines", {}),
        ])

    def test_ticket_holds_and_missing_acceptance_are_preserved(self):
        self.svc.tickets["SYN-2"]["detail"] = "Objective: Synthetic work."
        result = self.read("SYN-2")
        self.assertIn("No-auto execution hold", result["holds"])
        self.assertIn("Ticket acceptance criteria are not stated", result["holds"])
        self.assertEqual(result["status"], "held")

    def test_stale_missing_future_and_naive_source_timestamps_hold(self):
        for generated in (iso(NOW - 301), None, iso(NOW + 61), "2027-01-01T00:00:00"):
            with self.subTest(generated=generated):
                self.svc.engines["generated_at"] = generated
                result = self.read()
                self.assertIn("Engine observations are stale or their timestamp is unknown", result["holds"])
                self.assertFalse(any(c["eligible"] for c in result["candidates"]))
                self.assertFalse(result["source_current"])
                self.assertIsNone(result["expires_at"])
        self.svc.engines["generated_at"] = iso(NOW)
        self.svc.engines["stale"] = True
        result = self.read()
        self.assertIn("Engine observations are stale or their timestamp is unknown", result["holds"])
        self.assertFalse(result["source_current"])
        self.assertIsNone(result["expires_at"])

    def test_fresh_snapshot_does_not_refresh_an_old_probe(self):
        self.svc.engines["engines"][0]["probe"] = {"at": iso(NOW - 301), "ok": True}
        local = self.read()["candidates"][0]
        self.assertIn("Completion probe is stale or its timestamp is unknown", local["reasons"])
        self.assertIn("Engine probe does not qualify this model for the ticket", local["reasons"])

    def test_stopped_failed_and_inert_routes_report_precise_reasons(self):
        self.svc.engines["engines"][0].update(state="stopped", listening=False, probe={"at": iso(NOW), "ok": False})
        self.svc.engines["routing"]["routes"][0]["inert"] = True
        row = self.read()["candidates"][0]
        for reason in ("Route is disabled or its enabled state is unknown",
                       "Engine is not observed serving and listening", "Completion probe did not report success"):
            self.assertIn(reason, row["reasons"])

    def test_unsupported_unready_duplicate_and_malformed_inventory_is_unavailable(self):
        fixtures = [None, {}, {"error": "synthetic failure"}]
        unready = observation()
        unready["routing"]["inventory"]["ready"] = "true"
        fixtures.append(unready)
        duplicate = observation()
        duplicate["routing"]["routes"].append(deepcopy(duplicate["routing"]["routes"][0]))
        fixtures.append(duplicate)
        invalid = observation()
        invalid["routing"]["routes"][0]["model"] = "model\nunsafe label"
        fixtures.append(invalid)
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                self.svc.engines = fixture
                result = self.read()
                self.assertEqual(result["status"], "unavailable")
                self.assertEqual(result["candidates"], [])
                self.assertIsNone(result["expires_at"])
                self.assertFalse(result["source_current"])

    def test_engine_endpoint_outage_preserves_ticket_holds(self):
        self.svc.engine_status = 503
        self.svc.engines = {"error": "synthetic outage"}
        result = self.read("SYN-2")
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("No-auto execution hold", result["holds"])
        self.assertIn("HTTP 503", result["reasons"][0])

    def test_wrong_ticket_does_not_read_engine_inventory(self):
        self.svc.tickets["SYN-1"] = ticket("SYN-9")
        result = self.read()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["ticket"], {"key": "SYN-1", "revision": ""})
        self.assertIn("does not match the requested key", result["reasons"][0])
        self.assertEqual(len(self.svc.requests), 1)

    def test_empty_inventory_is_held_not_a_recommendation(self):
        self.svc.engines["routing"]["routes"] = []
        result = self.read()
        self.assertEqual(result["status"], "held")
        self.assertIn("No model routes were observed", result["reasons"])

    def test_explicit_origin_is_required_and_remote_origin_is_refused(self):
        with self.assertRaisesRegex(ValueError, "No ticket service configured"):
            ticket_route("SYN-1", cfg={})
        with self.assertRaisesRegex(ValueError, "local HTTP"):
            ticket_route("SYN-1", cfg={}, origin="https://example.com")
        self.assertEqual(self.svc.requests, [])

    def test_imported_origin_overrides_changed_config_for_same_ticket_key(self):
        other = RoutingService()
        try:
            with tempfile.TemporaryDirectory() as directory:
                ledger = Ledger(Path(directory) / "ledger.sqlite")
                try:
                    ledger.import_ticket(key="SYN-1", origin=self.svc.origin, revision="synthetic-revision",
                                         title="Synthetic", objective="Synthetic work", acceptance="Tests pass",
                                         context="Synthetic context", holds=[])
                    link = ledger.links("SYN-1")["links"][0]
                finally:
                    ledger.close()
                # Both services contain the same key and work definition. The
                # imported source, not the newly configured source, owns it.
                result = ticket_route(link["ticket_key"], origin=link["origin"],
                                      cfg={"ticket_service": {"origin": other.origin}}, now=NOW)
                self.assertEqual(result["source"], self.svc.origin + "/api/engines")
                self.assertEqual(len(self.svc.requests), 2)
                self.assertEqual(other.requests, [])
        finally:
            other.close()

    def test_cli_json_and_table_do_not_create_a_ledger_or_service(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.json"
            config.save(self.cfg, config_path)
            env = {k: v for k, v in os.environ.items() if not k.startswith("TASKRIVET_")}
            env.update(HOME=directory, TASKRIVET_CONFIG=str(config_path),
                       TASKRIVET_DB=str(root / "ledger.sqlite"), TASKRIVET_SESSION_DIR=str(root / "sessions"))
            for fmt in ("json", "table"):
                command = [sys.executable, "-m", "taskrivet", "ticket-route", "SYN-1", "--format", fmt]
                result = subprocess.run(command, cwd=REPO, env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                if fmt == "json":
                    self.assertEqual(json.loads(result.stdout)["status"], "held")
                else:
                    self.assertIn("Routing", result.stdout)
                    self.assertIn("unranked", result.stdout)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["config.json"])


if __name__ == "__main__":
    unittest.main()
