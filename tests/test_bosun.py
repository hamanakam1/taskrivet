import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from taskrivet.bosun import MAX_FRAME, normalize, snapshot


class BosunTests(unittest.TestCase):
    def fixture(self, body, declared_size=None, permissions=0o600):
        directory = tempfile.TemporaryDirectory(prefix='br-', dir='/tmp')
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)/'s'
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path)); path.chmod(permissions); server.listen(1); server.settimeout(2)
        received=[]
        def serve():
            try:
                conn,_=server.accept()
                with conn:
                    conn.settimeout(2)
                    header=conn.recv(4)
                    if len(header)==4:
                        size=struct.unpack('!I',header)[0]
                        data=bytearray()
                        while len(data)<size:
                            part=conn.recv(size-len(data))
                            if not part: break
                            data.extend(part)
                        received.append(json.loads(data))
                    conn.sendall(struct.pack('!I',declared_size if declared_size is not None else len(body)))
                    # Deliberately fragmented frame.
                    for i in range(0,len(body),7): conn.sendall(body[i:i+7])
                    extra=conn.recv(1024)
                    if extra: received.append(extra)
            except (OSError,ValueError): pass
            finally: server.close()
        thread=threading.Thread(target=serve,daemon=True);thread.start()
        self.addCleanup(thread.join,3)
        return path,received,thread

    def message(self):
        return {'t':'snapshot','seq':8,'server':{'protocol':1},'sessions':[{'name':'demo','display':'Demo','agent':'claude','path':'/private/not-exported'}], 'statuses':{'demo':{'state':'done','source':'hook'}}, 'config':{'credential':'not-exported'}}

    def test_snapshot_sends_only_hello_and_never_accepts_work(self):
        path,received,thread=self.fixture(json.dumps(self.message()).encode())
        result=snapshot(path);thread.join(2)
        self.assertEqual(len(received),1)
        self.assertEqual(received[0]['t'],'hello')
        self.assertTrue(result['sessions'][0]['turn_finished'])
        self.assertEqual(result['sessions'][0]['task_acceptance'],'not_evaluated')
        self.assertNotIn('config',result)
        self.assertNotIn('path',result['sessions'][0])
        self.assertFalse(result['execution_authorized'])

    def test_rejects_oversized_frames(self):
        path,_,_=self.fixture(b'',MAX_FRAME+1)
        with self.assertRaises(ValueError): snapshot(path)

    def test_rejects_truncation(self):
        path,_,_=self.fixture(b'{}',50)
        with self.assertRaises((ValueError,TimeoutError)): snapshot(path,timeout=.15)

    def test_rejects_insecure_socket(self):
        path,_,_=self.fixture(b'{}',permissions=0o666)
        with self.assertRaisesRegex(ValueError,'permissions'): snapshot(path)

    def test_unknown_states_and_protocol_version(self):
        m=self.message();m['statuses']['demo']={'state':'new_state','source':'new_source'}
        self.assertEqual(normalize(m)['sessions'][0]['activity'],'unknown')
        m['server']['protocol']=2
        with self.assertRaises(ValueError): normalize(m)

    def test_non_socket_rejected(self):
        with tempfile.NamedTemporaryFile() as f:
            with self.assertRaises(ValueError): snapshot(f.name)
