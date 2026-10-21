import unittest
from taskrivet.dashboard import endpoint, project_payload

class DashboardTests(unittest.TestCase):
    def payload(self, **changes):
        p={'tickets':[{'kind':'work','key':'synthetic-1','title':'Fix fixture','project':'Example','stage':'planned','priority':1,'readiness':{'verdict':'READY','verified':True},'detail_head':'not authorized for autonomous execution','tags':['no-auto']}], 'stats':{'total':200},'generated_at':'2026-01-01T00:00:00Z','stale':False}
        p.update(changes)
        return p
    def test_local_only_no_credentials_or_query(self):
        for url in ('https://example.com','http://example.com','http://127.0.0.1@evil.test','http://user@localhost','http://localhost/a','http://localhost?x=1'):
            with self.assertRaises(ValueError): endpoint(url,'planned',0)
        self.assertEqual(endpoint('http://127.0.0.1:7878','planned',100),'http://127.0.0.1:7878/api/tix?status=planned&limit=100&offset=100')
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
