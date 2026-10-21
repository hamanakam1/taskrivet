"""Synthetic source-owner fixtures; never imports a real ticket service."""
import unittest
from taskrivet.dashboard_bridge import reconcile, START, END

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.card={'status':'blocked','notes':'Operator note','revision':'fixture-revision'}
        self.writes=[];self.conflict=False
        self.status={'repo':'a/b','last_poll':1,'responses':{'review_code_change':2},'coverage':{'events':{'page_complete':False,'error':None}}}
    def read_card(self,ticket):return self.card.copy() if self.card else None
    def update_notes(self,ticket,notes,expected_revision):
        self.writes.append((ticket,notes,expected_revision))
        if self.conflict:raise ValueError('conflict')
        self.card['notes']=notes
    def test_preserves_source_status_and_notes_with_cas(self):
        result=reconcile(self,123,self.status)
        self.assertTrue(result['dashboard_readback']);self.assertEqual(self.card['status'],'blocked')
        self.assertTrue(self.card['notes'].startswith('Operator note'))
        self.assertEqual(self.writes[0][2],'fixture-revision')
        reconcile(self,123,self.status);self.assertEqual(self.card['notes'].count(START),1)
    def test_conflict_does_not_claim_success(self):
        self.conflict=True
        with self.assertRaisesRegex(ValueError,'conflict'):reconcile(self,123,self.status)
        self.assertEqual(self.card['notes'],'Operator note')
    def test_malformed_block_never_writes(self):
        self.card['notes']=END+'\n'+START
        with self.assertRaisesRegex(ValueError,'Malformed'):reconcile(self,123,self.status)
        self.assertFalse(self.writes)
    def test_missing_target_never_creates(self):
        self.card=None
        with self.assertRaisesRegex(ValueError,'does not exist'):reconcile(self,123,self.status)
        self.assertFalse(self.writes)
