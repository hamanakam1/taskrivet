import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from taskrivet.core import Conflict, Ledger


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'ledger.sqlite'
        self.l = Ledger(self.path)
        self.l.add_task('a', 'Fix search', 'Regression passes', scope=['repo/search'], token_budget=100)

    def tearDown(self):
        self.l.close()
        self.temp.cleanup()

    def start(self):
        return self.l.start('a', 'worker')['session_id']

    def cp(self, sid, tokens=10, evidence='diff:1'):
        return self.l.checkpoint(sid, 'progress', evidence, 'review', tokens)

    def test_lease_token_monotonic_across_resume(self):
        first = self.l.start('a', 'worker')
        self.assertEqual(first['lease_token'], 'a-1')
        sid = first['session_id']
        self.l.pause('a', sid, 'operator hold')
        second = self.l.resume('a', sid)
        self.assertEqual(second['lease_token'], 'a-2')
        self.l.pause('a', sid, 'still holding')
        third = self.l.resume('a', sid)
        self.assertEqual(third['lease_token'], 'a-3')

    def test_stale_lease_token_rejected_after_resume(self):
        started = self.l.start('a', 'worker')
        sid = started['session_id']
        token = started['lease_token']
        self.l.pause('a', sid, 'operator hold')
        resumed = self.l.resume('a', sid)
        self.assertEqual(self.l.checkpoint(sid, 'progress', 'diff:1', 'review', 10, lease_token=resumed['lease_token'])['status'], 'active')
        with self.assertRaises(Conflict): self.l.checkpoint(sid, 'progress', 'diff:2', 'review', 20, lease_token=token)
        with self.assertRaises(Conflict): self.l.fail(sid, 'tool', 'Stopped', lease_token=token)
        with self.assertRaises(Conflict): self.l.finish(sid, 'done', lease_token=token)

    def test_attempts_record_outcome_and_expose_in_detail(self):
        started = self.l.start('a', 'worker')
        attempt_id = started['attempt_id']
        sid = started['session_id']
        self.assertEqual(self.l.detail('a')['attempts'][0]['id'], attempt_id)
        self.assertEqual(self.l.detail('a')['attempts'][0]['outcome'], 'running')
        self.l.checkpoint(sid, 'progress', 'diff:1', 'review', 10)
        self.l.fail(sid, 'tool', 'Missing compiler', lease_token=started['lease_token'])
        self.assertEqual(self.l.detail('a')['attempts'][0]['outcome'], 'failed')
        self.l.decide('a', 'retry', 'Compiler available')
        self.assertEqual(self.l.detail('a')['attempts'][0]['outcome'], 'retry')
        second = self.l.start('a', 'worker')
        self.assertNotEqual(second['attempt_id'], attempt_id)
        self.l.checkpoint(second['session_id'], 'progress', 'diff:3', 'review', 5, lease_token=second['lease_token'])
        self.l.finish(second['session_id'], 'tests pass', lease_token=second['lease_token'])
        self.l.decide('a', 'accept', 'Reviewed')
        self.assertEqual(self.l.detail('a')['attempts'][1]['outcome'], 'accepted')

    def test_receipts_record_claim_and_evidence_idempotently(self):
        started = self.l.start('a', 'worker')
        attempt_id = started['attempt_id']
        claim = self.l.receipt(attempt_id, 'a', 'claim', f"{attempt_id}:claim", status='claimed')
        self.assertEqual(claim['action'], 'claim')
        self.assertEqual(len(self.l.receipts(attempt_id)), 1)
        self.assertEqual(self.l.receipt(attempt_id, 'a', 'claim', f"{attempt_id}:claim", status='claimed')['id'], claim['id'])
        self.assertEqual(len(self.l.receipts(attempt_id)), 1)
        sid = started['session_id']
        self.l.checkpoint(sid, 'progress', 'diff:1', 'review', 10, lease_token=started['lease_token'])
        self.l.finish(sid, 'tests pass', lease_token=started['lease_token'])
        self.assertEqual([r['action'] for r in self.l.receipts(attempt_id)], ['claim', 'evidence'])
        attempt = self.l.db.execute("SELECT * FROM attempts WHERE session_id=?", (sid,)).fetchone()
        evidence = self.l.receipt(attempt['id'], 'a', 'evidence', f"{attempt['id']}:evidence")
        self.assertEqual(evidence['action'], 'evidence')
        self.assertEqual(len(self.l.receipts(attempt['id'])), 2)
        self.assertTrue(self.l.detail('a')['receipts'])

    def test_events_carry_attempt_id_source_revision_and_deduplicate_replays(self):
        started = self.l.start('a', 'worker')
        attempt_id = started['attempt_id']
        started_events = [e for e in self.l.events() if e["type"] == "session.started"]
        self.assertEqual(len(started_events), 1)
        self.assertEqual(started_events[0]["attempt_id"], attempt_id)
        self.l.event("task.updated", 'a', source_revision=7, note="bump")
        updated = [e for e in self.l.events() if e["type"] == "task.updated"]
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["source_revision"], 7)
        self.l.record("agent.launched", 'a', tool="codex", terminal="t-1", session=started['session_id'])
        self.l.record("agent.launched", 'a', tool="codex", terminal="t-1", session=started['session_id'])
        launches = [e for e in self.l.events() if e["type"] == "agent.launched"]
        self.assertEqual(len(launches), 1)

    def test_accept_requires_finished_session(self):
        with self.assertRaises(Conflict): self.l.decide('a', 'accept', 'looks fine')
        sid = self.start()
        with self.assertRaises(Conflict): self.l.finish(sid, 'done')
        self.cp(sid)
        self.assertEqual(self.l.finish(sid, 'tests pass')['status'], 'review')
        self.assertEqual(self.l.decide('a', 'accept', 'reviewed')['status'], 'accepted')
        self.assertEqual(self.l.status()['metrics']['accepted'], 1)
        self.assertIsNone(self.l.status()['metrics']['measured_token_savings'])

    def test_concurrent_claim_has_one_winner(self):
        def claim(n):
            ledger = Ledger(self.path)
            try:
                return ledger.start('a', str(n))
            except Conflict:
                return None
            finally:
                ledger.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(claim, range(4)))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_scope_conflict(self):
        self.start()
        self.l.add_task('b', 'Another change', 'Tests pass', scope=['repo/search'])
        with self.assertRaises(Conflict): self.l.start('b', 'another')
        self.l.add_task('c', 'Independent change', 'Tests pass', scope=['repo/other'])
        self.l.start('c', 'independent')

    def test_expiry_blocks_until_reconciled_and_preserves_scope(self):
        sid = self.start()
        self.l.db.execute('UPDATE sessions SET lease_until=? WHERE id=?', (time.time()-1, sid))
        with self.assertRaises(Conflict): self.cp(sid)
        self.assertEqual(self.l.task('a')['status'], 'blocked')
        self.l.add_task('b', 'Other', 'Pass', scope=['repo/search'])
        with self.assertRaises(Conflict): self.l.start('b', 'other')
        self.assertEqual(self.l.status()['failures'][0]['category'], 'lease_expired')
        self.l.decide('a', 'retry', 'Old worker confirmed stopped')
        new = self.start()
        self.assertNotEqual(sid, new)
        with self.assertRaises(Conflict): self.cp(sid)

    def test_repeated_evidence_blocks_and_failure_persists(self):
        sid = self.start()
        self.cp(sid, 10)
        self.cp(sid, 20)
        self.assertEqual(self.cp(sid, 30)['status'], 'blocked')
        self.assertEqual(self.l.status()['failures'][0]['category'], 'no_progress')
        with self.assertRaises(Conflict): self.l.finish(sid, 'done')
        self.l.decide('a', 'retry', 'Stopped old worker and changed approach')
        self.assertEqual(len(self.l.status()['failures']), 1)

    def test_budget_survives_retry(self):
        sid = self.start()
        self.cp(sid, 70)
        self.l.fail(sid, 'tool', 'Missing compiler')
        self.l.decide('a', 'retry', 'Compiler available; old worker stopped')
        new = self.start()
        self.assertEqual(self.cp(new, 30)['status'], 'blocked')
        self.l.decide('a', 'retry', 'Attempt another worker')
        with self.assertRaises(Conflict): self.start()
        self.assertEqual(self.l.status()['metrics']['reported_tokens'], 100)

    def test_usage_cannot_decrease_or_be_negative(self):
        sid = self.start()
        self.cp(sid, 30)
        with self.assertRaises(Conflict): self.cp(sid, 20)
        with self.assertRaises(ValueError): self.cp(sid, -1)
        self.assertEqual(self.l.status()['metrics']['reported_tokens'], 30)

    def test_context_deduplicates_and_reports_expiry(self):
        one = self.l.add_context('a', 'Useful context', 'source-1')
        two = self.l.add_context('a', 'Useful context', 'source-2')
        self.assertEqual(one['hash'], two['hash'])
        self.l.add_context('a', 'Old context', 'old', ttl=1)
        self.l.db.execute('UPDATE task_context SET expires=0 WHERE source=?', ('old',))
        result = self.l.pack('a')
        self.assertEqual(len(result['packet']['context']), 1)
        self.assertEqual(result['omitted'][0]['reason'], 'expired')

    def test_context_budget_preserves_mandatory_fields(self):
        base = self.l.pack('a')['packet_bytes']
        self.l.add_context('a', '界' * 500, 'unicode')
        result = self.l.pack('a', base + 10)
        self.assertLessEqual(result['packet_bytes'], base + 10)
        self.assertEqual(result['packet']['acceptance'], 'Regression passes')
        self.assertEqual(result['omitted'][0]['reason'], 'byte_budget')
        with self.assertRaises(Conflict): self.l.pack('a', 10)

    def test_context_priority_and_latest_checkpoint(self):
        sid = self.start()
        self.cp(sid)
        self.l.add_context('a', 'low', 'low', priority=1)
        self.l.add_context('a', 'high', 'high', priority=100)
        result = self.l.pack('a')
        self.assertEqual(result['packet']['context'][0]['body'], 'high')
        self.assertEqual(result['packet']['checkpoint']['next_step'], 'review')

    def test_routing_rejects_unknown_paid_stale_and_incapable(self):
        for name, cost, kinds, limit in [('local','zero_incremental',['code'],8000),('paid','paid',['code'],8000),('unknown','unknown',['code'],8000),('wrong','zero_incremental',['design'],8000),('small','zero_incremental',['code'],100)]:
            self.l.profile(name, kinds, limit, cost)
        self.l.profile('stale', ['code'], 8000, 'zero_incremental')
        self.l.db.execute('UPDATE profiles SET verified_until=0 WHERE id=?', ('stale',))
        result = self.l.route('a')
        self.assertFalse(result['execution_authorized'])
        self.assertEqual([r['profile'] for r in result['options'] if r['eligible']], ['local'])
        self.assertTrue(all(r['quality_estimate'] is None for r in result['options']))

    def test_failure_recurrence_and_event_cursor(self):
        for _ in range(2):
            sid = self.start()
            self.l.fail(sid, 'tool', 'Compiler missing')
            self.l.decide('a', 'retry', 'Worker stopped; retry requested')
        self.assertEqual(self.l.status()['failures'][0]['occurrences'], 2)
        events = self.l.events()
        cursor = events[-2]['seq']
        self.assertEqual(len(self.l.events(cursor)), 1)

    def test_persistence_and_permissions(self):
        sid = self.start()
        self.cp(sid)
        other = Ledger(self.path)
        try:
            self.assertEqual(other.pack('a')['packet']['checkpoint']['evidence'], 'diff:1')
        finally:
            other.close()
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_invalid_input_rolls_back(self):
        before = len(self.l.events())
        with self.assertRaises(ValueError): self.l.add_task('bad', '', 'yes')
        with self.assertRaises(ValueError): self.l.start('a', 'worker', -1)
        self.assertEqual(len(self.l.events()), before)
        self.assertEqual(self.l.task('a')['status'], 'ready')

    def test_cli_refuses_stale_lease_token(self):
        cmd = [sys.executable, '-m', 'taskrivet', '--db', str(self.path)]
        started = subprocess.run(cmd + ['start', 'a', '--owner', 'worker'], capture_output=True)
        payload = json.loads(started.stdout)
        token = payload['lease_token']
        sid = payload['session_id']
        ok = subprocess.run(cmd + ['checkpoint', sid, '--summary', 'progress', '--evidence', 'diff:1', '--next', 'review', '--tokens', '10', '--lease-token', token], capture_output=True)
        self.assertEqual(ok.returncode, 0)
        stale = subprocess.run(cmd + ['checkpoint', sid, '--summary', 'progress', '--evidence', 'diff:2', '--next', 'review', '--tokens', '20', '--lease-token', 'a-999'], capture_output=True)
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn('stale lease token', json.loads(stale.stderr)['error'])

    def test_cli_packet_matches_budget_and_errors_are_json(self):
        self.l.add_context('a', '界 context', 'test')
        cmd = [sys.executable, '-m', 'taskrivet', '--db', str(self.path)]
        result = subprocess.run(cmd + ['pack','a','--max-bytes','1000','--packet-only'], capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertLessEqual(len(result.stdout), 1000)
        self.assertEqual(json.loads(result.stdout)['objective'], 'Fix search')
        result = subprocess.run(cmd + ['start','missing','--owner','worker'], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('unknown task', json.loads(result.stderr)['error'])


    def test_detail_reports_session_context_and_evidence(self):
        sid = self.start()
        self.cp(sid, tokens=25, evidence='diff:1')
        self.l.add_context('a', 'reference body', 'test source', priority=5)
        view = self.l.detail('a')
        self.assertEqual(view['task']['id'], 'a')
        self.assertEqual(view['task']['scope'], ['repo/search'])
        self.assertEqual(view['task']['reported_tokens'], 25)
        self.assertEqual(view['task']['remaining_tokens'], 75)
        self.assertEqual(view['session']['id'], sid)
        self.assertEqual(view['session']['status'], 'active')
        self.assertGreater(view['session']['lease_remaining_seconds'], 0)
        self.assertEqual(view['checkpoints'][0]['evidence'], 'diff:1')
        self.assertEqual(view['context'][0]['source'], 'test source')
        self.assertEqual(view['context'][0]['bytes'], len(b'reference body'))
        self.assertTrue(view['events'])
        self.assertEqual(view['pack']['items'], 1)
        self.assertIsNone(view['pack']['error'])
        self.assertIn('not measured cost', view['provenance'])

    def test_detail_claims_show_shared_resource_keys(self):
        self.l.add_task('b', 'Overlapping change', 'Tests pass', scope=['repo/search'])
        self.l.start('b', 'other-worker')
        view = self.l.detail('a')
        self.assertEqual(view['claims'][0]['task'], 'b')
        self.assertEqual(view['claims'][0]['status'], 'running')
        self.assertEqual(view['claims'][0]['shared_keys'], ['repo/search'])

    def test_detail_of_unknown_task_is_an_error(self):
        with self.assertRaises(ValueError): self.l.detail('missing')

    def test_cli_detail_reads_one_task(self):
        sid = self.start()
        self.cp(sid)
        cmd = [sys.executable, '-m', 'taskrivet', '--db', str(self.path)]
        result = subprocess.run(cmd + ['detail', '--task', 'a'], capture_output=True)
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['session']['id'], sid)
        self.assertEqual(payload['checkpoints'][0]['summary'], 'progress')
        result = subprocess.run(cmd + ['detail', '--task', 'missing'], capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('unknown task', json.loads(result.stderr)['error'])


if __name__ == '__main__':
    unittest.main()
