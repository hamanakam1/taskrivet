import unittest
import contextlib
import io
from unittest.mock import patch
from taskrivet.dashboard import endpoint, project_payload, project_session_context
from taskrivet.cli import parser

class DashboardTests(unittest.TestCase):
    def test_destination_must_be_explicit(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser().parse_args(['dashboard-preview'])
        self.assertEqual(parser().parse_args(['dashboard-preview', '--url', 'http://localhost:8080']).url,
                         'http://localhost:8080')
        from taskrivet.dashboard import preview
        with patch('taskrivet.dashboard.build_opener') as opener:
            with self.assertRaises(ValueError): preview('')
            opener.assert_not_called()

    def payload(self, **changes):
        p={'tickets':[{'kind':'work','key':'synthetic-1','title':'Fix fixture','project':'Example','stage':'planned','priority':1,'readiness':{'verdict':'READY','verified':True},'detail_head':'not authorized for autonomous execution','tags':['no-auto']}], 'stats':{'total':200},'generated_at':'2026-01-01T00:00:00Z','stale':False}
        p.update(changes)
        return p
    def test_local_only_no_credentials_or_query(self):
        for url in ('https://example.com','http://example.com','http://127.0.0.1@evil.test','http://user@localhost','http://localhost/a','http://localhost?x=1'):
            with self.assertRaises(ValueError): endpoint(url,'planned',0)
        self.assertEqual(endpoint('http://127.0.0.1:8080','planned',100),'http://127.0.0.1:8080/api/tix?status=planned&limit=100&offset=100')
    def test_preserves_holds_never_authorizes_and_minimizes_data(self):
        p=self.payload();p['tickets'][0]['secret_extra']='PRIVATE'
        r=project_payload(p,'local','planned',0,1767225600)
        self.assertFalse(r['stale']);self.assertFalse(r['dispatch_enabled'])
        row=r['tickets'][0]
        self.assertFalse(row['execution_authorized']);self.assertIn('No-auto execution hold',row['reasons'])
        self.assertIn('Explicit execution denial in source excerpt',row['reasons']);self.assertNotIn('PRIVATE',str(r))
        self.assertTrue(r['has_more']);self.assertEqual(r['returned'],1)
    def test_stale_and_missing_readiness_fail_closed(self):
        p=self.payload();p['tickets'][0]['readiness']={}
        r=project_payload(p,'local','planned',0,1767226000)
        self.assertTrue(r['stale']);self.assertIn('Readiness: UNKNOWN',r['tickets'][0]['reasons'])
    def test_error_and_loading_are_not_empty_success(self):
        for extra in ({'errors':['source unavailable']},{'loading':True},{'refresh_error':'bad'}):
            with self.assertRaises(ValueError):project_payload(self.payload(**extra),'local','planned',0)
    def test_cases_are_not_misrepresented_as_work_tickets(self):
        p=self.payload();p['tickets'].append({'kind':'case','key':'fake-case'})
        self.assertEqual(project_payload(p,'local','planned',0)['returned'],1)

    def test_session_context_adapter_minimizes_and_denies_authority(self):
        envelope = {
            'schema': 'taskrivet.ticket-context.v1',
            'ticket': {'key': 'SYN-1', 'title': 'Synthetic ticket', 'detail': 'private'},
            'task': {'id': 'demo', 'objective': 'Show context', 'acceptance': 'Badge visible', 'scope': ['private']},
            'session': {'id': 's1', 'status': 'active', 'binding': 'joined', 'shared_count': 2},
            'authority': {'execution_authorized': True, 'ticket_mutation': True},
            'provenance': {'source': 'fixture', 'generated_at': '2026-01-01T00:00:00Z'},
        }
        result = project_session_context(envelope)
        self.assertEqual(result['session']['binding'], 'joined')
        self.assertEqual(result['session']['shared_count'], 2)
        self.assertFalse(result['authority']['execution_authorized'])
        self.assertFalse(result['authority']['ticket_mutation'])
        self.assertNotIn('private', str(result))

    def test_session_context_adapter_rejects_unknown_schema(self):
        with self.assertRaises(ValueError): project_session_context({'schema': 'other'})
