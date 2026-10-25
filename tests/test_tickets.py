"""Ticket reads against a synthetic local service."""
from datetime import datetime, timedelta, timezone
import unittest

from synthetic import FakeTicketService, ticket
from taskrivet.dashboard import SourceUnavailable
from taskrivet.tickets import extract, get_ticket, list_tickets, revision


class TicketReadTests(unittest.TestCase):
    def setUp(self):
        self.svc = FakeTicketService([
            ticket("SYN-1"),
            ticket("SYN-2", tags=["no-auto"],
                   detail="Objective: Draft the fixture.\nThis card is not authorized for autonomous execution.\n"),
            ticket("SYN-3", kind="case", title="Synthetic case"),
            ticket("SYN-4", stage="blocked", readiness={"verdict": "NEEDS_REVIEW", "verified": False}),
        ])

    def tearDown(self):
        self.svc.close()

    def test_list_filters_kind_and_reports_holds_without_authorizing(self):
        r = list_tickets(self.svc.origin, limit=10)
        self.assertEqual([t["key"] for t in r["tickets"]], ["SYN-1", "SYN-2", "SYN-4"])
        self.assertFalse(r["stale"])
        self.assertFalse(r["execution_authorized"])
        rows = {t["key"]: t for t in r["tickets"]}
        self.assertEqual(rows["SYN-1"]["holds"], [])
        self.assertIn("No-auto execution hold", rows["SYN-2"]["holds"])
        self.assertIn("Explicit execution denial in source excerpt", rows["SYN-2"]["holds"])
        self.assertIn("Readiness is not verified", rows["SYN-4"]["holds"])
        self.assertIn("Source stage requires reconciliation or review", rows["SYN-4"]["holds"])
        self.assertEqual(r["source_total"], 4)
        self.assertFalse(r["has_more"])
        self.assertTrue(all(method == "GET" for method, _, _ in self.svc.requests))

    def test_query_and_paging_are_forwarded(self):
        r = list_tickets(self.svc.origin, q="widget", status="planned", limit=1)
        self.assertEqual(self.svc.requests[-1][2], {"status": "planned", "limit": "1", "offset": "0", "q": "widget"})
        self.assertTrue(r["has_more"])
        self.assertEqual(list_tickets(self.svc.origin, kind="case")["tickets"][0]["key"], "SYN-3")

    def test_stale_or_incomplete_lists_fail_closed(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.svc.list_extra = {"generated_at": old}
        self.assertTrue(list_tickets(self.svc.origin)["stale"])
        self.svc.list_extra = {"stale": True}
        self.assertTrue(list_tickets(self.svc.origin)["stale"])
        for extra in ({"errors": ["database locked"]}, {"loading": True}, {"refresh_error": "boom"}):
            self.svc.list_extra = extra
            with self.assertRaises(ValueError):
                list_tickets(self.svc.origin)

    def test_outages_are_unavailable_not_empty(self):
        self.svc.status_code = 503
        with self.assertRaises(SourceUnavailable):
            list_tickets(self.svc.origin)
        with self.assertRaises(SourceUnavailable):
            get_ticket(self.svc.origin, "SYN-1")
        closed = FakeTicketService([])
        origin = closed.origin
        closed.close()
        with self.assertRaises(SourceUnavailable):
            list_tickets(origin, timeout=2)

    def test_rejects_remote_origins_and_bad_input_before_any_request(self):
        for origin in ("https://example.com", "http://example.com:80", "http://localhost:1/api", "http://u@localhost:1"):
            with self.assertRaises(ValueError):
                list_tickets(origin)
        with self.assertRaises(ValueError):
            list_tickets(self.svc.origin, limit=0)
        with self.assertRaises(ValueError):
            list_tickets(self.svc.origin, status="Planned!")
        with self.assertRaises(ValueError):
            get_ticket(self.svc.origin, "../etc/passwd")
        self.assertEqual(self.svc.requests, [])

    def test_detail_extracts_objective_acceptance_and_dependency_holds(self):
        self.svc.tickets["SYN-1"]["links_resolved"]["blocked_by"] = [{"key": "SYN-9", "title": "Upstream"}]
        s = get_ticket(self.svc.origin, "SYN-1")
        self.assertEqual(s["objective"], "Make the synthetic widget render.")
        self.assertEqual(s["acceptance"], "The widget test passes.")
        self.assertIn("Blocking dependencies (state unknown): SYN-9", s["holds"])
        self.assertEqual(s["links"]["blocked_by"][0]["key"], "SYN-9")
        self.assertFalse(s["execution_authorized"])
        self.assertEqual(s["origin"], self.svc.origin)

    def test_detail_bounds_large_text(self):
        self.svc.tickets["SYN-1"]["detail"] = "x" * 100_000
        s = get_ticket(self.svc.origin, "SYN-1")
        self.assertLess(len(s["detail"].encode()), 25_000)
        self.assertTrue(s["detail"].endswith("[truncated by Taskrivet]"))

    def test_missing_ticket_is_an_error(self):
        with self.assertRaisesRegex(ValueError, "not found"):
            get_ticket(self.svc.origin, "SYN-404")

    def test_revision_tracks_the_work_definition_only(self):
        base = ticket("SYN-1")
        self.assertEqual(revision(base), revision(dict(base, stage="progress", tags=["x"])))
        self.assertNotEqual(revision(base), revision(dict(base, detail="Objective: something else")))

    def test_extract_reads_inline_and_block_labels(self):
        text = "**Objective:**\n- Ship the widget\n- Keep it small\n\nAcceptance criteria: tests pass"
        self.assertEqual(extract(text, "objective"), "- Ship the widget\n- Keep it small")
        self.assertEqual(extract(text, "acceptance"), "tests pass")
        self.assertIsNone(extract("No labels here", "objective"))


if __name__ == "__main__":
    unittest.main()
