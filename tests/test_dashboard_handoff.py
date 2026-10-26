import io
import json
import unittest
from unittest.mock import patch

from taskrivet.handoff import submit


class Response:
    def __init__(self, payload):
        self.data = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit=-1): return self.data


def result(**changes):
    payload = {
        'ok': True, 'schema': 'taskrivet.handoff-receipt.v1', 'request_id': 'req-1', 'requires_local_confirmation': True,
        'dispatch_enabled': False,
        'authority': {'context_readonly': True, 'ticket_mutation': False, 'acceptance': False, 'execution_authorized': False},
        'receipt': {'request_id': 'req-1', 'context_hash': 'a' * 64},
    }
    payload.update(changes)
    return payload


class HandoffTests(unittest.TestCase):
    def test_success_returns_confirmation_gated_receipt(self):
        with patch('taskrivet.handoff.build_opener') as factory:
            factory.return_value.open.return_value = Response(result())
            value = submit('http://127.0.0.1:7878', {'schema': 'taskrivet.ticket-context.v1'})
        self.assertEqual(value['receipt']['request_id'], 'req-1')
        request = factory.return_value.open.call_args.args[0]
        self.assertEqual(request.method, 'POST')
        self.assertIn('/api/taskrivet/handoff', request.full_url)

    def test_remote_origin_is_rejected_before_network(self):
        with patch('taskrivet.handoff.build_opener') as factory:
            with self.assertRaises(ValueError): submit('https://example.test', {})
            factory.assert_not_called()

    def test_authorizing_response_is_rejected(self):
        with patch('taskrivet.handoff.build_opener') as factory:
            factory.return_value.open.return_value = Response(result(dispatch_enabled=True))
            with self.assertRaisesRegex(ValueError, 'enables dispatch'):
                submit('http://localhost:7878', {})

    def test_missing_receipt_is_rejected(self):
        with patch('taskrivet.handoff.build_opener') as factory:
            factory.return_value.open.return_value = Response(result(receipt=None))
            with self.assertRaisesRegex(ValueError, 'receipt'):
                submit('http://localhost:7878', {})

