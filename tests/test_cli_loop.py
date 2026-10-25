"""The ticket-loop commands through the real command line."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from synthetic import FakeTicketService, cleanup, short_dir, stop_service, ticket, wait_for_exit, write_tool

REPO = Path(__file__).resolve().parents[1]


class CliLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.base = short_dir()
        self.svc = FakeTicketService([ticket("SYN-1"), ticket("SYN-2", tags=["no-auto"])])
        self.tool = write_tool(root / "fake-agent")
        self.config = root / "config.json"
        self.runs = root / "runs"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("TASKRIVET_")}
        # A temporary HOME keeps every default path (runs, sessions, config) out of the real one.
        self.env.update(HOME=str(root), TASKRIVET_CONFIG=str(self.config), TASKRIVET_DB=str(root / "ledger.sqlite"),
                        TASKRIVET_SESSION_DIR=str(self.base / "s"), PYTHONPATH=str(REPO))

    def tearDown(self):
        self.svc.close()
        stop_service(self.base / "s")
        cleanup(self.base)
        self.temp.cleanup()

    def cli(self, *args, code=0):
        done = subprocess.run([sys.executable, "-m", "taskrivet", *args], capture_output=True, text=True,
                              env=self.env, cwd=REPO, timeout=60)
        self.assertEqual(done.returncode, code, done.stderr)
        return done

    def configure(self):
        self.cli("config", "set", "ticket_service.origin", self.svc.origin)
        self.cli("config", "set", "runs_dir", str(self.runs))
        self.cli("config", "set", "launchers.codex", json.dumps({"argv": [str(self.tool), "{prompt}"]}))

    def test_config_commands_keep_the_file_private(self):
        self.configure()
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        got = json.loads(self.cli("config", "get", "ticket_service.origin").stdout)
        self.assertEqual(got["value"], self.svc.origin)
        bad = self.cli("config", "set", "ticket_service.origin", "https://example.com", code=2)
        self.assertIn("local HTTP", json.loads(bad.stderr)["error"])
        shown = json.loads(self.cli("config", "show").stdout)
        self.assertTrue(shown["exists"])
        self.cli("config", "unset", "launchers.codex")
        self.assertNotIn("launchers", json.loads(self.cli("config", "show").stdout)["settings"])

    def test_ticket_reads_in_json_and_table_form(self):
        self.configure()
        listing = json.loads(self.cli("tickets").stdout)
        self.assertEqual([t["key"] for t in listing["tickets"]], ["SYN-1", "SYN-2"])
        table = self.cli("--format", "table", "tickets").stdout
        self.assertIn("KEY", table)
        self.assertIn("SYN-2", table)
        self.assertIn("freshness current", table)
        self.cli("config", "set", "ticket_service.ticket_url", self.svc.origin + "/#/ticket/{key}")
        detail = json.loads(self.cli("ticket", "SYN-2").stdout)
        self.assertEqual(detail["holds"], ["No-auto execution hold"])
        self.assertIsNone(detail["local"])
        self.assertEqual(detail["url"], self.svc.origin + "/#/ticket/SYN-2")
        shown = self.cli("ticket", "SYN-2", "--format", "table").stdout
        self.assertIn("taskrivet work SYN-2 --tool NAME --ack", shown)
        self.assertIn("/#/ticket/SYN-2", shown)
        self.assertTrue(all(method == "GET" for method, _, _ in self.svc.requests))

    def test_missing_configuration_and_unknown_targets_fail_with_json(self):
        err = json.loads(self.cli("tickets", code=2).stderr)
        self.assertIn("No ticket service configured", err["error"])
        err = json.loads(self.cli("handback", "SYN-404", code=2).stderr)
        self.assertIn("No task or linked ticket", err["error"])
        self.assertIn("taskrivet:", self.cli("--format", "table", "handback", "SYN-404", code=2).stderr)

    def test_work_requires_acknowledged_holds_and_supports_a_dry_run(self):
        self.configure()
        err = json.loads(self.cli("work", "SYN-2", "--tool", "codex", code=2).stderr)
        self.assertEqual(err["type"], "HoldsPending")
        self.assertEqual(err["holds"], ["No-auto execution hold"])
        plan = json.loads(self.cli("work", "SYN-2", "--tool", "codex", "--ack", "--dry-run").stdout)
        self.assertTrue(plan["dry_run"])
        self.assertEqual(plan["launcher"]["source"], "local config")
        self.assertEqual(json.loads(self.cli("status").stdout)["tasks"], [])

    def test_import_launch_links_and_watch(self):
        self.configure()
        imported = json.loads(self.cli("ticket-import", "SYN-1").stdout)
        self.assertTrue(imported["created"])
        launched = json.loads(self.cli("work", "SYN-1", "--tool", "codex", "--cwd", self.temp.name).stdout)
        self.assertEqual(launched["task_id"], imported["task_id"])
        self.assertEqual(Path(launched["run_dir"]).parent.parent, self.runs)
        self.assertEqual(Path(launched["context"]).stat().st_mode & 0o777, 0o600)
        sessions = json.loads(self.cli("sessions").stdout)
        self.assertEqual(sessions["service"], "running")
        self.assertIn(launched["terminal"]["id"], [t["id"] for t in sessions["terminals"]])
        links = json.loads(self.cli("links", "--ticket", "SYN-1").stdout)["links"]
        self.assertEqual(links[0]["agent"]["terminal"], launched["terminal"]["id"])
        self.assertIn("SYN-1", self.cli("--format", "table", "links").stdout)
        wait_for_exit(self.base / "s", launched["terminal"]["id"])
        replay = self.cli("attach", launched["terminal"]["id"][:8], "--no-follow").stdout
        self.assertIn("TICKET:SYN-1", replay)
        events = [json.loads(line) for line in self.cli("watch", "--after", "0", "--count", "1").stdout.splitlines()]
        self.assertIn("agent.launched", [e["type"] for e in events])
        self.assertIn("source.imported", self.cli("--format", "table", "watch", "--after", "0", "--count", "1",
                                                  "--ticket", "SYN-1").stdout)

    def test_sessions_and_doctor_report_without_starting_anything(self):
        sessions = json.loads(self.cli("sessions").stdout)
        self.assertEqual((sessions["service"], sessions["terminals"]), ("not running", []))
        self.cli("config", "set", "ticket_service.origin", self.svc.origin)
        done = subprocess.run([sys.executable, "-m", "taskrivet", "doctor", "--offline"], capture_output=True,
                              text=True, env=self.env, cwd=REPO, timeout=60)
        report = json.loads(done.stdout)
        checks = {c["check"]: c for c in report["checks"]}
        self.assertEqual(checks["ticket_service"]["status"], "skipped")
        self.assertEqual(checks["session_service"]["detail"], "Not running; it starts on demand")
        self.assertEqual(checks["ledger"]["status"], "warn")
        self.assertFalse((self.base / "s").exists())
        self.assertFalse(Path(self.env["TASKRIVET_DB"]).exists())
        self.assertEqual(self.svc.requests, [])


if __name__ == "__main__":
    unittest.main()
