"""JSON-first CLI for humans and dashboard adapters."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from .core import Ledger


def parser():
    p = argparse.ArgumentParser(description='Taskrivet: purposeful agent work, bounded context, visible failures.')
    p.add_argument('--db', default=os.environ.get('TASKRIVET_DB', str(Path.home() / '.taskrivet' / 'ledger.sqlite')))
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('init')
    sub.add_parser('status')
    b = sub.add_parser('bosun-status'); b.add_argument('--socket', required=True)
    e = sub.add_parser('events'); e.add_argument('--after', type=int, default=0)
    a = sub.add_parser('task-add')
    a.add_argument('id'); a.add_argument('--objective', required=True); a.add_argument('--acceptance', required=True)
    a.add_argument('--kind', default='code'); a.add_argument('--scope', action='append', required=True)
    a.add_argument('--token-budget', type=int, default=8000)
    s = sub.add_parser('start'); s.add_argument('task'); s.add_argument('--owner', required=True); s.add_argument('--lease', type=int, default=900)
    c = sub.add_parser('checkpoint'); c.add_argument('session'); c.add_argument('--summary', required=True)
    c.add_argument('--evidence', required=True); c.add_argument('--next', required=True); c.add_argument('--tokens', type=int, required=True)
    c.add_argument('--lease', type=int, default=900)
    f = sub.add_parser('fail'); f.add_argument('session'); f.add_argument('--category', required=True); f.add_argument('--summary', required=True)
    f = sub.add_parser('finish'); f.add_argument('session'); f.add_argument('--evidence', required=True)
    for name in ['accept', 'retry', 'cancel']:
        d = sub.add_parser(name); d.add_argument('task'); d.add_argument('--reason', required=True)
    c = sub.add_parser('context-add'); c.add_argument('task'); c.add_argument('--file', required=True)
    c.add_argument('--source', required=True); c.add_argument('--priority', type=int, default=0); c.add_argument('--ttl', type=int)
    c = sub.add_parser('pack'); c.add_argument('task'); c.add_argument('--max-bytes', type=int, default=12000)
    c.add_argument('--packet-only', action='store_true', help='Emit compact bounded packet without diagnostics')
    c = sub.add_parser('profile-add'); c.add_argument('id'); c.add_argument('--kind', action='append', required=True)
    c.add_argument('--context-limit', type=int, required=True); c.add_argument('--cost', choices=['zero_incremental','paid','unknown'], required=True)
    c.add_argument('--ttl', type=int, default=3600)
    c = sub.add_parser('route'); c.add_argument('task'); c.add_argument('--required-context', type=int, default=4096)
    return p


def main():
    a = parser().parse_args()
    ledger = None
    try:
        if a.command == 'bosun-status':
            from .bosun import snapshot
            print(json.dumps(snapshot(a.socket), indent=2))
            return
        ledger = Ledger(a.db)
        cmd = a.command
        if cmd == 'init': result = {'schema': 1, 'status': 'ready', 'dispatch_enabled': False}
        elif cmd == 'status': result = ledger.status()
        elif cmd == 'events': result = ledger.events(a.after)
        elif cmd == 'task-add': result = ledger.add_task(a.id, a.objective, a.acceptance, a.kind, a.scope, a.token_budget)
        elif cmd == 'start': result = ledger.start(a.task, a.owner, a.lease)
        elif cmd == 'checkpoint': result = ledger.checkpoint(a.session, a.summary, a.evidence, a.next, a.tokens, a.lease)
        elif cmd == 'fail': result = ledger.fail(a.session, a.category, a.summary)
        elif cmd == 'finish': result = ledger.finish(a.session, a.evidence)
        elif cmd in ('accept','retry','cancel'): result = ledger.decide(a.task, cmd, a.reason)
        elif cmd == 'context-add': result = ledger.add_context(a.task, Path(a.file).read_text(), a.source, a.priority, a.ttl)
        elif cmd == 'pack':
            result = ledger.pack(a.task, a.max_bytes)
            if a.packet_only:
                sys.stdout.write(json.dumps(result['packet'], ensure_ascii=False, separators=(',', ':')))
                return
        elif cmd == 'profile-add': result = ledger.profile(a.id, a.kind, a.context_limit, a.cost, a.ttl)
        elif cmd == 'route': result = ledger.route(a.task, a.required_context)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({'error': str(exc), 'type': type(exc).__name__}), file=sys.stderr)
        raise SystemExit(2)
    finally:
        if ledger is not None:
            ledger.close()
