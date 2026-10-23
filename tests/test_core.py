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

    def test_scope_defaults_only_when_omitted(self):
        for scope in ([], '', {}, (), False, 0, 'repo/search', ['']):
            with self.subTest(scope=scope):
                before = self.l.events()
                with self.assertRaises(ValueError):
                    self.l.add_task('invalid', 'Fix search', 'Tests pass', scope=scope)
                self.assertEqual(self.l.events(), before)
                with self.assertRaisesRegex(ValueError, 'unknown task'):
                    self.l.task('invalid')
        task = self.l.add_task('default', 'Fix search', 'Tests pass')
        self.assertEqual(json.loads(task['scope']), ['default'])
        self.l.add_task('overlap', 'Other work', 'Tests pass', scope=['default'])
        self.l.start('default', 'worker')
        with self.assertRaises(Conflict):
            self.l.start('overlap', 'another')

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

    def test_profile_kinds_reject_malformed_collections_without_mutation(self):
        self.l.profile('existing', ['design'], 8000, 'zero_incremental')
        for kinds in ('decode', {'code': True}, ('code',), [], None, False, 1, ['']):
            for profile_id in ('new', 'existing'):
                with self.subTest(kinds=kinds, profile_id=profile_id):
                    before = self.l.events()
                    with self.assertRaises(ValueError):
                        self.l.profile(profile_id, kinds, 8000, 'zero_incremental')
                    self.assertEqual(self.l.events(), before)
                    options = self.l.route('a')['options']
                    self.assertEqual([option['profile'] for option in options], ['existing'])
                    self.assertFalse(options[0]['eligible'])
        self.l.profile('existing', ['design', 'code'], 8000, 'zero_incremental')
        route = self.l.route('a')
        self.assertTrue(route['options'][0]['eligible'])
        self.assertFalse(route['execution_authorized'])

    def test_routing_excludes_malformed_legacy_kinds(self):
        self.l.profile('legacy', ['code'], 8000, 'zero_incremental')
        for kinds in ('decode', {'code': True}, [], None, 1, ['code', '']):
            with self.subTest(kinds=kinds):
                self.l.db.execute('UPDATE profiles SET kinds=? WHERE id=?',
                                  (json.dumps(kinds), 'legacy'))
                route = self.l.route('a')
                self.assertFalse(route['options'][0]['eligible'])
                self.assertIn('invalid declared task kinds', route['options'][0]['reasons'][0])
                self.assertFalse(route['execution_authorized'])

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
