import unittest

from taskrivet.ticket_context import SCHEMA, build


class TicketContextTests(unittest.TestCase):
    def detail(self):
        return {
            "task": {"id": "badge-demo", "objective": "Show context",
                     "acceptance": "Badges visible", "scope": ["synthetic/demo"]},
            "session": {"id": "session-owner", "status": "active", "binding": "owner"},
            "sessions": [
                {"id": "session-owner", "status": "active"},
                {"id": "session-joined", "status": "active"},
                {"id": "old", "status": "finished"},
            ],
        }

    def test_owner_context_is_bounded_and_non_authorizing(self):
        result = build(self.detail(), ticket={"key": "SYN-1", "revision": "r1",
                                              "title": "Synthetic ticket"},
                       generated_at="2026-01-01T00:00:00Z")
        self.assertEqual(result["schema"], SCHEMA)
        self.assertEqual(result["session"]["binding"], "owner")
        self.assertEqual(result["session"]["shared_count"], 2)
        self.assertTrue(result["authority"]["context_readonly"])
        self.assertFalse(result["authority"]["ticket_mutation"])
        self.assertFalse(result["authority"]["acceptance"])
        self.assertFalse(result["authority"]["execution_authorized"])
        self.assertEqual(result["provenance"]["generated_at"], "2026-01-01T00:00:00Z")

    def test_missing_ticket_is_standalone(self):
        result = build(self.detail())
        self.assertIsNone(result["ticket"]["key"])
        self.assertEqual(result["session"]["binding"], "standalone")

    def test_untrusted_binding_fails_closed_to_owner(self):
        detail = self.detail()
        detail["session"]["binding"] = "authorized"
        result = build(detail, ticket={"key": "SYN-1"})
        self.assertEqual(result["session"]["binding"], "owner")


if __name__ == "__main__":
    unittest.main()
