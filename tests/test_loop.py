"""The operator ticket loop: holds, launch, links, and confirmed reports."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from synthetic import FakeTicketService, cleanup, short_dir, stop_service, ticket, wait_for_exit, write_adapter, write_tool
from taskrivet.core import Conflict, Ledger
from taskrivet.loop import (
    MARKER_RESERVE, REPORT_BYTES, HandbackUnconfirmed, HoldsPending, handback, import_snapshot, links_view,
    report_body, sessions_view, work)
from taskrivet.session_client import SessionError
from taskrivet.tickets import get_ticket

NO_AUTO = "No-auto execution hold"


class WorkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.base = short_dir()
        self.sessions = self.base / "s"
        self.env = patch.dict(os.environ, {"TASKRIVET_SESSION_DIR": str(self.sessions)})
        self.env.start()
        self.svc = FakeTicketService([ticket("SYN-1"), ticket("SYN-2", tags=["no-auto"])])
        self.bin = root / "bin"
        self.bin.mkdir()
        write_tool(self.bin / "codex")
        self.db = root / "ledger.sqlite"
        self.ledger = Ledger(self.db)
        self.workdir = root / "repo"
        self.workdir.mkdir()
        self.cfg = {"ticket_service": {"origin": self.svc.origin}, "runs_dir": str(root / "runs"),
                    "workdir": str(self.workdir)}

    def tearDown(self):
        self.ledger.close()
        self.svc.close()
        stop_service(self.sessions)
        self.env.stop()
        cleanup(self.base)
        self.temp.cleanup()

    def work(self, key, **kw):
        return work(self.ledger, self.db, key, "codex", cfg=self.cfg, paths=[str(self.bin)], **kw)

    def test_holds_must_be_acknowledged_before_anything_is_written(self):
        with self.assertRaises(HoldsPending) as caught:
            self.work("SYN-2")
        self.assertEqual(caught.exception.details["holds"], [NO_AUTO])
        self.assertEqual(self.ledger.status()["tasks"], [])
        self.assertFalse(self.sessions.exists())

    def test_dry_run_changes_nothing(self):
        plan = self.work("SYN-2", acknowledge=True, dry_run=True)
        self.assertTrue(plan["dry_run"])
        self.assertEqual(plan["launcher"]["executable"], str(self.bin / "codex"))
        self.assertTrue(plan["launcher"]["prompt"])
        self.assertEqual(plan["cwd"], os.path.realpath(self.workdir))
        self.assertEqual(self.ledger.status()["tasks"], [])
        self.assertFalse(self.sessions.exists())

    def test_launches_the_agent_with_context_and_records_the_link(self):
        r = self.work("SYN-2", acknowledge=True)
        record, output = wait_for_exit(self.sessions, r["terminal"]["id"])
        self.assertEqual(record["exitCode"], 0)
        self.assertEqual((record["kind"], record["ref"], record["task"], record["session"]),
                         ("agent", "SYN-2", r["task_id"], r["session_id"]))
        for expected in ("ARGS:Taskrivet run for ticket SYN-2", "SESSION:" + r["session_id"],
                         "TASK:" + r["task_id"], "TICKET:SYN-2", "CONTEXT:" + r["context"],
                         "DB:" + os.path.abspath(self.db), "PWD:" + os.path.realpath(self.workdir)):
            self.assertIn(expected, output)
        context = Path(r["context"])
        self.assertEqual(context.stat().st_mode & 0o777, 0o600)
        self.assertEqual(context.parent.stat().st_mode & 0o777, 0o700)
        text = context.read_text()
        self.assertIn("## Holds the operator acknowledged", text)
        self.assertIn(NO_AUTO, text)
        self.assertIn("Make the synthetic widget render.", text)
        self.assertIn("checkpoint " + r["session_id"], text)
        self.assertIn("Do not change the ticket's stage", text)
        for name in ("ticket.json", "packet.json"):
            self.assertEqual((context.parent / name).stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.ledger.task(r["task_id"])["status"], "running")
        self.assertEqual(self.ledger.task_source(r["task_id"])["acknowledged"], [NO_AUTO])
        launched = [e for e in self.ledger.events() if e["type"] == "agent.launched"]
        self.assertEqual(launched[-1]["data"]["terminal"], r["terminal"]["id"])
        self.assertEqual(launched[-1]["data"]["run_dir"], r["run_dir"])
        link = links_view(self.ledger, self.db, "SYN-2")["links"][0]
        self.assertEqual((link["agent"]["tool"], link["agent"]["terminal_state"], link["agent"]["exit_code"]),
                         ("codex", "exited", 0))
        self.assertEqual(sessions_view(self.db)["service"], "running")

    def test_second_launch_while_running_is_refused(self):
        self.work("SYN-1")
        with self.assertRaisesRegex(Conflict, "bound to task ticket-syn-1"):
            self.work("SYN-1")

    def test_acknowledgement_carries_over_until_the_holds_change(self):
        snap = get_ticket(self.svc.origin, "SYN-2")
        import_snapshot(self.ledger, snap, acknowledge=True)
        self.assertTrue(self.work("SYN-2", dry_run=True)["dry_run"])
        self.svc.tickets["SYN-2"]["needs_decision"] = True
        with self.assertRaises(HoldsPending) as caught:
            self.work("SYN-2", dry_run=True)
        self.assertIn("Operator decision required", caught.exception.details["holds"])

    def test_failed_terminal_start_is_recorded_as_unknown(self):
        class Broken:
            def __init__(self, _directory):
                pass

            def connect(self, start=True):
                raise SessionError("synthetic outage")

            def close(self):
                pass

        with self.assertRaises(SessionError):
            self.work("SYN-1", client_factory=Broken)
        task = self.ledger.status()["tasks"][0]
        self.assertEqual(task["status"], "blocked")
        failure = self.ledger.detail(task["id"])["failures"][0]
        self.assertEqual(failure["category"], "terminal_start")
        self.assertTrue(failure["summary"].startswith("Terminal start outcome unknown"))


class HandbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.ledger = Ledger(root / "ledger.sqlite")
        self.state = root / "adapter-state.json"
        self.cfg = {"ticket_adapter": {"argv": [sys.executable, str(write_adapter(root)), str(self.state)]}}
        imported = self.ledger.import_ticket(key="SYN-1", origin="http://127.0.0.1:9", revision="r1",
                                             title="Synthetic", objective="Do it", acceptance="Tests pass",
                                             context="ticket text", holds=[])
        self.task = imported["task_id"]

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def finish(self):
        sid = self.ledger.start(self.task, "worker")["session_id"]
        self.ledger.checkpoint(sid, "Widget renders", "test_widget passed", "operator review", 1200)
        self.ledger.finish(sid, "unit tests pass")

    def adapter(self):
        return json.loads(self.state.read_text()) if self.state.exists() else None

    def send(self, **kw):
        return handback(self.ledger, self.task, cfg=self.cfg, environ={}, **kw)

    def test_nothing_to_report_without_a_session_or_note(self):
        with self.assertRaisesRegex(ValueError, "Nothing to report"):
            self.send()
        self.assertIn("Operator note: checked by hand", report_body(self.ledger, self.task, "checked by hand"))

    def test_report_leaves_room_for_the_marker_line(self):
        sid = self.ledger.start(self.task, "worker")["session_id"]
        self.ledger.checkpoint(sid, "x" * 9000, "evidence", "next", 10)
        body = report_body(self.ledger, self.task)
        self.assertLessEqual(len(body.encode("utf-8")), REPORT_BYTES - MARKER_RESERVE)
        marker = "taskrivet-handback:" + "0" * 16
        self.assertLessEqual(len(("\n\n" + marker).encode("utf-8")), MARKER_RESERVE)
        self.assertLessEqual(len((body + "\n\n" + marker).encode("utf-8")), REPORT_BYTES)

    def test_preview_never_calls_the_adapter(self):
        self.finish()
        preview = self.send(note="Looks right")
        self.assertTrue(preview["preview"])
        for expected in ("Taskrivet report for SYN-1", "finished; awaiting operator review", "Summary: Widget renders",
                         "Evidence: test_widget passed", "Finish evidence: unit tests pass",
                         "Self-reported tokens: 1200 (not measured billing)", "Operator note: Looks right",
                         "does not accept the work"):
            self.assertIn(expected, preview["body"])
        self.assertIsNone(self.adapter())
        self.assertEqual(self.ledger.handbacks(self.task), [])

    def test_confirm_posts_once_and_reads_back(self):
        self.finish()
        sent = self.send(confirm=True)
        self.assertTrue(sent["delivered"])
        self.assertFalse(sent["already_present"])
        state = self.adapter()
        self.assertEqual(state["calls"], ["find", "post", "find"])
        self.assertEqual(len(state["posts"]), 1)
        post = state["posts"][0]
        self.assertEqual((post["ticket"], post["sender"], post["role"]), ("SYN-1", "Taskrivet", "agent"))
        self.assertTrue(post["body"].endswith(sent["handback"]["marker"]))
        self.assertEqual(self.ledger.handbacks(self.task)[0]["status"], "delivered")
        again = self.send(confirm=True)
        self.assertTrue(again["already_present"])
        self.assertEqual(self.adapter()["calls"], ["find", "post", "find"])

    def test_lost_readback_is_reconciled_without_a_duplicate(self):
        self.finish()
        self.state.write_text(json.dumps({"posts": [], "calls": [], "hide": 1}))
        with self.assertRaises(HandbackUnconfirmed) as caught:
            self.send(confirm=True)
        self.assertEqual(caught.exception.details["handback"]["status"], "pending")
        self.assertEqual(caught.exception.details["handback"]["attempts"], 1)
        settled = self.send(confirm=True)
        self.assertTrue(settled["already_present"])
        state = self.adapter()
        self.assertEqual(len(state["posts"]), 1)
        self.assertEqual(state["calls"], ["find", "post", "find", "find"])
        self.assertEqual(self.ledger.handbacks(self.task)[0]["status"], "delivered")

    def test_agent_sessions_and_missing_adapters_cannot_post(self):
        self.finish()
        with self.assertRaisesRegex(Conflict, "operator shell"):
            handback(self.ledger, self.task, cfg=self.cfg, confirm=True, environ={"TASKRIVET_SESSION": "x"})
        with self.assertRaisesRegex(ValueError, "No ticket adapter"):
            handback(self.ledger, self.task, cfg={}, confirm=True, environ={})
        self.assertIsNone(self.adapter())
        self.assertEqual(self.ledger.handbacks(self.task), [])

    def test_adapter_errors_leave_the_report_pending(self):
        self.finish()
        broken = {"ticket_adapter": {"argv": [sys.executable, "-c", "import sys; sys.exit(3)"]}}
        with self.assertRaises(HandbackUnconfirmed) as caught:
            handback(self.ledger, self.task, cfg=broken, confirm=True, environ={})
        self.assertIn("status 3", str(caught.exception))
        self.assertEqual(self.ledger.handbacks(self.task)[0]["status"], "pending")

    def test_a_ticket_key_selects_its_latest_task(self):
        self.finish()
        preview = handback(self.ledger, "SYN-1", cfg=self.cfg, environ={})
        self.assertEqual(preview["task_id"], self.task)
        with self.assertRaisesRegex(ValueError, "No task or linked ticket"):
            handback(self.ledger, "SYN-404", cfg=self.cfg, environ={})


if __name__ == "__main__":
    unittest.main()
