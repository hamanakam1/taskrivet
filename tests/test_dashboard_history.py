import json
from unittest.mock import patch

from taskrivet.handoff import history


class Response:
    def __init__(self, payload): self.data = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit=-1): return self.data


def payload(**changes):
    value = {'ok': True, 'mode': 'evidence-only', 'dispatch_enabled': False, 'execution_authorized': False,
             'handoffs': [{'request_id': 'r1', 'evidence_only': True, 'execution_authorized': False}]}
    value.update(changes)
    return value


def test_history_accepts_evidence_only_response():
    with patch('taskrivet.handoff.build_opener') as factory:
        factory.return_value.open.return_value = Response(payload())
        assert history('http://127.0.0.1:7878', 1)['mode'] == 'evidence-only'


def test_history_rejects_authorizing_response():
    with patch('taskrivet.handoff.build_opener') as factory:
        factory.return_value.open.return_value = Response(payload(execution_authorized=True))
        try:
            history('http://localhost:7878')
        except ValueError as exc:
            assert 'evidence-only' in str(exc)
        else:
            raise AssertionError('unsafe history was accepted')
