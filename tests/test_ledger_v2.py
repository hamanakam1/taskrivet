"""Ledger schema 2: ticket bindings, handback records, and the links view."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from taskrivet.core import SCHEMA_VERSION, Conflict, Ledger

V1 = """
CREATE TABLE tasks (id TEXT PRIMARY KEY, objective TEXT NOT NULL, acceptance TEXT NOT NULL,
    kind TEXT NOT NULL, scope TEXT NOT NULL, status TEXT NOT NULL, token_budget INTEGER NOT NULL, created REAL NOT NULL);
CREATE TABLE sessions (id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), owner TEXT NOT NULL,
    status TEXT NOT NULL, lease_until REAL NOT NULL, tokens INTEGER NOT NULL DEFAULT 0,
    progress TEXT NOT NULL DEFAULT '', stagnant INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE UNIQUE INDEX one_active ON sessions(task_id) WHERE status='active';
CREATE TABLE checkpoints (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
    summary TEXT NOT NULL, evidence TEXT NOT NULL, next_step TEXT NOT NULL, tokens INTEGER NOT NULL, created REAL NOT NULL);
CREATE TABLE contexts (hash TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE task_context (task_id TEXT NOT NULL REFERENCES tasks(id), hash TEXT NOT NULL REFERENCES contexts(hash),
    source TEXT NOT NULL, priority INTEGER NOT NULL, expires REAL, PRIMARY KEY(task_id, hash));
CREATE TABLE failures (id INTEGER PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
    session_id TEXT REFERENCES sessions(id), category TEXT NOT NULL, fingerprint TEXT NOT NULL,
    summary TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE profiles (id TEXT PRIMARY KEY, kinds TEXT NOT NULL, context_limit INTEGER NOT NULL,
    cost TEXT NOT NULL, verified_until REAL NOT NULL);
CREATE TABLE events (seq INTEGER PRIMARY KEY, type TEXT NOT NULL, task_id TEXT, data TEXT NOT NULL, created REAL NOT NULL);
"""

HOLD = "No-auto execution hold"


class LedgerV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "ledger.sqlite"
        self.ledgers = []

    def tearDown(self):
        for ledger in self.ledgers:
            ledger.close()
        self.temp.cleanup()

    def ledger(self):
        ledger = Ledger(self.path)
        self.ledgers.append(ledger)
        return ledger

    def imp(self, ledger, **changes):
        args = dict(key="SYN-1", origin="http://127.0.0.1:9", revision="r1", title="Synthetic", objective="Do it",
                    acceptance="Tests pass", context="ticket text", holds=[HOLD])
        args.update(changes)
        return ledger.import_ticket(**args)

    def test_migrates_a_v1_ledger_in_place(self):
        db = sqlite3.connect(self.path)
        db.executescript(V1)
        db.execute("INSERT INTO tasks VALUES ('old','Keep me','Still here','code','[\"old\"]','ready',100,1.0)")
        db.commit()
        db.close()
        ledger = self.ledger()
        self.assertEqual(ledger.schema_version(), SCHEMA_VERSION)
        self.assertEqual(ledger.task("old")["objective"], "Keep me")
        tables = {r[0] for r in ledger.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"task_sources", "handbacks"} <= tables)
        ledger.close()
        self.ledgers.remove(ledger)
        self.assertEqual(self.ledger().schema_version(), SCHEMA_VERSION)

    def test_import_is_idempotent_and_detects_changed_revisions(self):
        ledger = self.ledger()
        first = self.imp(ledger)
        again = self.imp(ledger)
        self.assertTrue(first["created"])
        self.assertFalse(again["created"])
        self.assertEqual(first["task_id"], "ticket-syn-1")
        self.assertEqual(again["task_id"], first["task_id"])
        self.assertIn("ticket:SYN-1", json.loads(first["task"]["scope"]))
        self.assertEqual(first["task"]["token_budget"], 400_000)
        with self.assertRaisesRegex(Conflict, "--refresh"):
            self.imp(ledger, revision="r2")
        refreshed = self.imp(ledger, revision="r2", refresh=True, context="new ticket text")
        self.assertTrue(refreshed["refreshed"])
        self.assertEqual(ledger.task_source(first["task_id"])["revision"], "r2")
        types = [e["type"] for e in ledger.events()]
        self.assertIn("source.imported", types)
        self.assertIn("source.refreshed", types)

    def test_acknowledgement_is_kept_only_while_the_holds_match(self):
        ledger = self.ledger()
        tid = self.imp(ledger, acknowledged=True)["task_id"]
        self.assertEqual(ledger.task_source(tid)["acknowledged"], [HOLD])
        self.imp(ledger)
        self.assertEqual(ledger.task_source(tid)["acknowledged"], [HOLD])
        self.imp(ledger, holds=[HOLD, "Operator decision required"])
        self.assertIsNone(ledger.task_source(tid)["acknowledged"])
        self.assertIn("holds.acknowledged", [e["type"] for e in ledger.events()])

    def test_different_origin_cannot_reuse_or_refresh_an_open_ticket_binding(self):
        ledger = self.ledger()
        tid = self.imp(ledger)["task_id"]
        before = ledger.task_source(tid)
        events = ledger.events()
        for changed in ({}, {"refresh": True, "revision": "foreign-revision", "context": "foreign context"}):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(Conflict, "another source origin"):
                    self.imp(ledger, origin="http://127.0.0.1:10", **changed)
                self.assertEqual(ledger.task_source(tid), before)
                self.assertEqual(ledger.events(), events)

    def test_closed_tasks_get_a_new_task_on_reimport(self):
        ledger = self.ledger()
        tid = self.imp(ledger)["task_id"]
        ledger.decide(tid, "cancel", "not now")
        self.assertIsNone(ledger.ticket_binding("SYN-1"))
        second = self.imp(ledger)
        self.assertEqual(second["task_id"], "ticket-syn-1-2")
        self.assertEqual(ledger.ticket_tasks("SYN-1"), [tid, "ticket-syn-1-2"])
        self.assertEqual(ledger.ticket_binding("SYN-1")["task_id"], "ticket-syn-1-2")

    def test_handback_marker_is_stable_until_delivered(self):
        ledger = self.ledger()
        tid = self.imp(ledger)["task_id"]
        a = ledger.stage_handback(tid, "first")
        b = ledger.stage_handback(tid, "second")
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(a["marker"], b["marker"])
        self.assertEqual(b["body"], "second")
        failed = ledger.settle_handback(a["id"], False, "timed out")
        self.assertEqual((failed["status"], failed["attempts"], failed["last_error"]), ("pending", 1, "timed out"))
        done = ledger.settle_handback(a["id"], True)
        self.assertEqual(done["status"], "delivered")
        self.assertIsNotNone(done["delivered"])
        c = ledger.stage_handback(tid, "third")
        self.assertNotEqual(c["marker"], a["marker"])
        self.assertEqual([h["status"] for h in ledger.handbacks(tid)], ["delivered", "pending"])

    def test_handbacks_need_a_ticket_link(self):
        ledger = self.ledger()
        ledger.add_task("plain", "Objective", "Acceptance")
        with self.assertRaisesRegex(ValueError, "not linked"):
            ledger.stage_handback("plain", "body")

    def test_links_join_session_agent_checkpoint_and_handback(self):
        ledger = self.ledger()
        tid = self.imp(ledger)["task_id"]
        sid = ledger.start(tid, "worker")["session_id"]
        ledger.record("agent.launched", tid, tool="codex", terminal="t-1", session=sid)
        ledger.checkpoint(sid, "Halfway", "diff:1", "finish", 10)
        row = ledger.links("SYN-1")["links"][0]
        self.assertEqual(row["origin"], "http://127.0.0.1:9")
        self.assertEqual(row["task_status"], "running")
        self.assertEqual(row["session"]["status"], "active")
        self.assertEqual(row["session"]["reported_tokens"], 10)
        self.assertEqual(row["agent"]["tool"], "codex")
        self.assertEqual(row["agent"]["terminal"], "t-1")
        self.assertEqual(row["checkpoint"]["summary"], "Halfway")
        self.assertIsNone(row["handback"])
        self.assertEqual(row["holds"], [HOLD])
        self.assertEqual(ledger.links("OTHER")["links"], [])


if __name__ == "__main__":
    unittest.main()
