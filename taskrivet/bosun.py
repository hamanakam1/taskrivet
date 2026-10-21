"""Read-only Bosun protocol-v1 snapshot adapter; never launches a daemon."""
import json
import os
from pathlib import Path
import socket
import stat
import struct
import time

MAX_FRAME = 16 * 1024 * 1024


def recv_exact(connection, length, deadline):
    data = bytearray()
    while len(data) < length:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Bosun snapshot deadline exceeded')
        connection.settimeout(remaining)
        chunk = connection.recv(min(length-len(data), 65536))
        if not chunk:
            raise ValueError('Bosun closed an incomplete frame')
        data.extend(chunk)
    return bytes(data)


def normalize(message):
    if not isinstance(message, dict) or message.get('t') != 'snapshot':
        raise ValueError('Expected a Bosun snapshot')
    server = message.get('server')
    if not isinstance(server, dict) or server.get('protocol') != 1:
        raise ValueError('Unsupported Bosun protocol version')
    sessions, statuses = message.get('sessions'), message.get('statuses')
    if not isinstance(sessions, list) or not isinstance(statuses, dict):
        raise ValueError('Malformed Bosun snapshot')
    result = []
    for item in sessions:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            raise ValueError('Malformed Bosun session')
        status = statuses.get(item['name'], {})
        if not isinstance(status, dict):
            raise ValueError('Malformed Bosun status')
        value = status.get('state', 'unknown')
        if value not in ('running','waiting','done','idle','error','unknown'):
            value = 'unknown'
        source = status.get('source', 'unknown')
        if source not in ('hook', 'detector'):
            source = 'unknown'
        result.append({'external_id':item['name'], 'display':item.get('display',item['name']),
                       'agent':item.get('agent'), 'activity':value, 'activity_source':source,
                       'turn_finished':value == 'done', 'task_acceptance':'not_evaluated'})
    return {'provider':'bosun', 'protocol':1, 'observed_at':time.time(), 'sequence':message.get('seq'),
            'sessions':result, 'read_only':True, 'execution_authorized':False,
            'note':'Snapshot observation only. Turn finished does not imply task acceptance.'}


def snapshot(socket_path, timeout=3.0):
    if not isinstance(timeout, (int, float)) or not 0 < timeout <= 30:
        raise ValueError('Timeout must be between 0 and 30 seconds')
    path = Path(socket_path).expanduser()
    metadata = path.lstat()
    if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise ValueError('Bosun socket must be a socket owned by the current user')
    if metadata.st_mode & 0o077:
        raise ValueError('Bosun socket must not grant group or other permissions')
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(str(path))
        hello = json.dumps({'t':'hello','protocol':1,'client':'taskrivet-observer/0.2'}).encode()
        conn.sendall(struct.pack('!I', len(hello)) + hello)
        size = struct.unpack('!I', recv_exact(conn,4,deadline))[0]
        if size == 0 or size > MAX_FRAME:
            raise ValueError('Invalid Bosun frame length')
        try:
            message = json.loads(recv_exact(conn,size,deadline))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('Invalid Bosun JSON') from exc
        return normalize(message)
