import os
from pathlib import Path
import tempfile
import time
import unittest
from taskrivet.tools import inventory, history_counts

class ToolTests(unittest.TestCase):
    def test_detection_never_executes_and_preserves_precedence(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder); a=p/'a'; b=p/'b'; a.mkdir(); b.mkdir()
            for d in (a,b):
                f=d/'codex'; f.write_text('#!/bin/sh\ntouch '+str(p/'EXECUTED')); f.chmod(0o700)
            (a/'plain').write_text('not executable')
            result=inventory(paths=[str(a),str(b)])
            tool=next(t for t in result['tools'] if t['id']=='codex')
            self.assertEqual(tool['executable'],str(a/'codex'))
            self.assertFalse((p/'EXECUTED').exists())
            self.assertEqual(result['installed'],1)
            self.assertEqual(tool['authentication'],'unknown')

    def test_history_excludes_arguments_old_entries_and_unknown_names(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'history'
            p.write_text(f': {int(time.time())}:0;codex SECRET\n: 1:0;codex old\nclaude PRIVATE\nunknown TOKEN\n')
            counts=history_counts(p,{'codex','claude'})
            self.assertEqual(counts,{'codex':{'recent_count':1,'undated_count':0},'claude':{'recent_count':0,'undated_count':1}})
            self.assertNotIn('SECRET',str(counts))

    def test_empty_and_missing_history(self):
        self.assertEqual(history_counts('/nonexistent/taskrivet-history',{'codex'}),{})
        result=inventory(paths=[])
        self.assertEqual(result['installed'],0)
        self.assertTrue(all(not t['installed'] for t in result['tools']))

    def test_catalog_discovers_over_one_hundred_without_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            for n in range(125):
                p=Path(folder)/f'custom-tool-{n}'
                p.write_text('#!/bin/sh\nexit 0\n');p.chmod(0o700)
            result=inventory(paths=[folder])
            self.assertEqual(result['installed'],125)
            self.assertEqual(sum(t['installed'] for t in result['tools']),125)
