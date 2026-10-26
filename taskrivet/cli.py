"""JSON-first CLI for humans and dashboard adapters."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from .core import Ledger

FORMATS = ('json', 'table')


def parser():
    fmt = argparse.ArgumentParser(add_help=False)
    fmt.add_argument('--format', choices=FORMATS, default=argparse.SUPPRESS,
                     help='json (default, stable) or table (for people)')
    p = argparse.ArgumentParser(description='Taskrivet: purposeful agent work, bounded context, visible failures.')
    p.add_argument('--db', default=os.environ.get('TASKRIVET_DB', str(Path.home() / '.taskrivet' / 'ledger.sqlite')))
    default_format = os.environ.get('TASKRIVET_FORMAT', 'json')
    p.add_argument('--format', choices=FORMATS, default=default_format if default_format in FORMATS else 'json',
                   help='json (default, stable) or table (for people)')
    sub = p.add_subparsers(dest='command', required=True)

    def add(name, **kw):
        return sub.add_parser(name, parents=[fmt], **kw)

    add('init')
    add('status')
    for command in ('github-poll','github-status'):
        g=add(command);g.add_argument('--repo',required=True);g.add_argument('--sync-db',default=str(Path.home()/'.taskrivet'/'github.sqlite'))
    g=add('github-cycle');g.add_argument('--config',required=True)
    d = add('dashboard-preview'); d.add_argument('--url', required=True, help='Explicit local ticket-service origin'); d.add_argument('--status', choices=['planned','backlog','progress','blocked','show_tell'], default='planned'); d.add_argument('--offset', type=int, default=0)
    b = add('tools'); b.add_argument('--history', action='store_true')
    o = add('opencode-sessions', help='List local OpenCode TUI session metadata')
    o.add_argument('--limit', type=int, default=60)
    o.add_argument('--project', default=None, help='Restrict the read to one working folder')
    o.add_argument('--max-projects', type=int, default=12)
    e = add('events'); e.add_argument('--after', type=int, default=0)
    d = add('detail', help='Read one task with its sessions, context, and evidence')
    d.add_argument('--task', required=True); d.add_argument('--session', default=None)
    a = add('task-add')
    a.add_argument('id'); a.add_argument('--objective', required=True); a.add_argument('--acceptance', required=True)
    a.add_argument('--kind', default='code'); a.add_argument('--scope', action='append', required=True)
    a.add_argument('--token-budget', type=int, default=8000)
    s = add('start'); s.add_argument('task'); s.add_argument('--owner', required=True); s.add_argument('--lease', type=int, default=900)
    c = add('checkpoint'); c.add_argument('session'); c.add_argument('--summary', required=True)
    c.add_argument('--evidence', required=True); c.add_argument('--next', required=True); c.add_argument('--tokens', type=int, required=True)
    c.add_argument('--lease', type=int, default=900)
    f = add('fail'); f.add_argument('session'); f.add_argument('--category', required=True); f.add_argument('--summary', required=True)
    f = add('finish'); f.add_argument('session'); f.add_argument('--evidence', required=True)
    for name in ['accept', 'retry', 'cancel']:
        d = add(name); d.add_argument('task'); d.add_argument('--reason', required=True)
    c = add('context-add'); c.add_argument('task'); c.add_argument('--file', required=True)
    c.add_argument('--source', required=True); c.add_argument('--priority', type=int, default=0); c.add_argument('--ttl', type=int)
    c = add('pack'); c.add_argument('task'); c.add_argument('--max-bytes', type=int, default=12000)
    c.add_argument('--packet-only', action='store_true', help='Emit compact bounded packet without diagnostics')
    c = add('profile-add'); c.add_argument('id'); c.add_argument('--kind', action='append', required=True)
    c.add_argument('--context-limit', type=int, required=True); c.add_argument('--cost', choices=['zero_incremental','paid','unknown'], required=True)
    c.add_argument('--ttl', type=int, default=3600)
    c = add('route'); c.add_argument('task'); c.add_argument('--required-context', type=int, default=4096)

    from .loop import DEFAULT_LEASE
    from .tickets import KINDS
    origin = 'Ticket-service origin; overrides ticket_service.origin in the private config'
    t = add('tickets', help='List tickets from the configured ticket service (read only)')
    t.add_argument('--q', '--search', dest='q', help='Search text')
    t.add_argument('--status', default='all', help='Source state such as planned, or all (default)')
    t.add_argument('--kind', choices=KINDS, default='work')
    t.add_argument('--limit', type=int, default=50); t.add_argument('--offset', type=int, default=0)
    t.add_argument('--url', help=origin)
    t = add('ticket', help='Read one ticket with its holds and local tasks (read only)')
    t.add_argument('key'); t.add_argument('--url', help=origin)
    t = add('ticket-route', help='Read model routing observations and qualification gaps; launches nothing')
    t.add_argument('key'); t.add_argument('--url', help=origin)
    t = add('ticket-import', help='Bind one ticket revision to a local task; launches nothing')
    t.add_argument('key'); t.add_argument('--url', help=origin)
    t.add_argument('--ack', action='store_true', help='Record that you reviewed the current holds; clears nothing')
    t.add_argument('--refresh', action='store_true', help='Attach a changed ticket revision to the open task')
    t.add_argument('--scope', action='append', help='Extra resource key to reserve, such as a repository path')
    t.add_argument('--token-budget', type=int, default=400_000)
    w = add('work', help='Import a ticket you chose, start a session, and open an agent terminal')
    w.add_argument('key'); w.add_argument('--tool', required=True, help='Agent CLI to launch, such as codex')
    w.add_argument('--url', help=origin)
    w.add_argument('--ack', action='store_true', help='Record that you reviewed the current holds; clears nothing')
    w.add_argument('--refresh', action='store_true', help='Attach a changed ticket revision to the open task')
    w.add_argument('--cwd', help='Working folder (default: config workdir, then the current folder)')
    w.add_argument('--lease', type=int, default=DEFAULT_LEASE, help='Session lease in seconds; checkpoints renew it')
    w.add_argument('--no-prompt', action='store_true', help='Open the tool without an initial prompt')
    w.add_argument('--dry-run', action='store_true', help='Show the launch plan without importing or starting')
    w.add_argument('--scope', action='append', help='Extra resource key to reserve')
    w.add_argument('--token-budget', type=int, default=400_000)
    h = add('handback', help='Preview a ticket report, or post it with --confirm')
    h.add_argument('target', help='Task id, or a ticket key for its latest task')
    h.add_argument('--confirm', action='store_true', help='Post the report through the configured ticket adapter')
    h.add_argument('--note', help='Operator note to include')
    l = add('links', help='Ticket-linked tasks with their session, agent terminal, and report state')
    l.add_argument('--ticket'); l.add_argument('--limit', type=int, default=200)
    l.add_argument('--no-live', action='store_true', help='Skip the session service check')
    add('sessions', help='Terminals in the session service for this ledger')
    t = add('attach', help='Replay and follow a terminal; Ctrl-] detaches')
    t.add_argument('id', help='Terminal id or a unique prefix of at least 4 characters')
    t.add_argument('--no-follow', action='store_true', help='Print the scrollback and return')
    t.add_argument('--no-input', action='store_true', help='Follow output without forwarding keystrokes')
    t = add('doctor', help='Check configuration, ticket service, ledger, sessions, and launchers')
    t.add_argument('--offline', action='store_true', help='Do not contact the ticket service')
    t = add('watch', help='Follow ledger events as they are recorded')
    t.add_argument('--interval', type=float, default=2.0); t.add_argument('--after', type=int)
    t.add_argument('--task'); t.add_argument('--ticket'); t.add_argument('--count', type=int, help='Stop after N polls')
    add('launchers', help='Agent launchers you can pick for work')
    c = add('config', help='Read or change the private local config')
    cs = c.add_subparsers(dest='config_command', required=True)
    cs.add_parser('show', parents=[fmt]); cs.add_parser('path', parents=[fmt])
    g = cs.add_parser('get', parents=[fmt]); g.add_argument('key')
    g = cs.add_parser('set', parents=[fmt]); g.add_argument('key'); g.add_argument('value', help='JSON value, or plain text')
    g = cs.add_parser('unset', parents=[fmt]); g.add_argument('key')
    return p


def emit(a, result, indent=2):
    if a.format == 'table':
        from .output import render
        sys.stdout.write(render(a.command, result).rstrip('\n') + '\n')
    else:
        print(json.dumps(result, indent=indent, ensure_ascii=False))


def report_error(a, exc):
    details = getattr(exc, 'details', None) or {}
    if getattr(a, 'format', 'json') == 'table':
        print(f'taskrivet: {exc}', file=sys.stderr)
        for hold in details.get('holds') or []:
            print(f'  - {hold}', file=sys.stderr)
        if details.get('handback'):
            h = details['handback']
            print(f"  handback {h.get('id')} is {h.get('status')} after {h.get('attempts')} attempt(s)", file=sys.stderr)
    else:
        print(json.dumps({'error': str(exc), 'type': type(exc).__name__, **details}, ensure_ascii=False), file=sys.stderr)


def config_command(a):
    from . import config as settings
    if a.config_command == 'show':
        return settings.describe()
    if a.config_command == 'path':
        return {'path': str(settings.config_path())}
    if a.config_command == 'get':
        return {'key': a.key, 'value': settings.get_value(a.key)}
    if a.config_command == 'set':
        settings.set_value(a.key, a.value)
        return {'key': a.key, 'value': settings.get_value(a.key), 'path': str(settings.config_path())}
    settings.unset_value(a.key)
    return {'key': a.key, 'removed': True, 'path': str(settings.config_path())}


def attach_command(a):
    from .session_client import SessionClient, ServiceNotRunning, attach, session_dir
    client = SessionClient(session_dir(a.db))
    try:
        try:
            client.connect(start=False)
        except ServiceNotRunning:
            raise ValueError('No session service is running for this ledger. Run: taskrivet sessions') from None
        result = attach(client, a.id, follow=not a.no_follow, interactive=False if a.no_input else None)
    finally:
        client.close()
    if result['state'] == 'exited':
        print(f"\r\n[terminal exited with code {result['exit_code']}]", file=sys.stderr)
    elif result['detached']:
        print(f"\r\n[detached; the terminal keeps running. Reattach: taskrivet attach {result['id']}]", file=sys.stderr)


def watch_command(a):
    if not 0.2 <= a.interval <= 3600:
        raise ValueError('Interval must be 0.2-3600 seconds')
    if a.count is not None and a.count < 1:
        raise ValueError('Count must be at least 1')
    from .output import event_line
    ledger = Ledger(a.db)
    try:
        after = ledger.last_event() if a.after is None else a.after
        polls = 0
        while True:
            ledger.reconcile()
            tasks = set(ledger.ticket_tasks(a.ticket)) if a.ticket else None
            for event in ledger.events(after):
                after = event['seq']
                if (a.task and event['task_id'] != a.task) or (tasks is not None and event['task_id'] not in tasks):
                    continue
                if a.format == 'table':
                    print(event_line(event), flush=True)
                else:
                    print(json.dumps(event, ensure_ascii=False, separators=(',', ':')), flush=True)
            polls += 1
            if a.count is not None and polls >= a.count:
                return
            time.sleep(a.interval)
    except KeyboardInterrupt:
        return
    finally:
        ledger.close()


def ticket_command(a):
    from . import config as settings
    from .tickets import get_ticket, list_tickets
    cfg = settings.load()
    origin = settings.ticket_origin(cfg, a.url)
    timeout = settings.ticket_timeout(cfg)
    if a.command == 'tickets':
        return list_tickets(origin, a.q, a.status, a.kind, a.limit, a.offset, timeout)
    snap = get_ticket(origin, a.key, timeout)
    if a.command == 'ticket':
        snap['url'] = settings.ticket_link(cfg, snap['key'])
        snap['local'] = None
        if Path(a.db).expanduser().exists():
            from .loop import links_view
            ledger = Ledger(a.db)
            try:
                snap['local'] = links_view(ledger, a.db, snap['key'])['links']
            finally:
                ledger.close()
        return snap
    from .loop import import_snapshot
    ledger = Ledger(a.db)
    try:
        return import_snapshot(ledger, snap, acknowledge=a.ack, refresh=a.refresh, scope=a.scope,
                               token_budget=a.token_budget)
    finally:
        ledger.close()


def main(argv=None):
    a = parser().parse_args(argv)
    ledger = None
    try:
        if a.command == 'github-cycle':
            from .github_cycle import cycle
            emit(a, cycle(a.config), indent=None);return
        if a.command in ('github-poll','github-status'):
            from .github_sync import GitHubSync
            sync=GitHubSync(a.sync_db)
            try: emit(a, sync.poll(a.repo,max_pages=20) if a.command=='github-poll' else sync.status(a.repo))
            finally: sync.close()
            return
        if a.command == 'dashboard-preview':
            from .dashboard import preview
            emit(a, preview(a.url,a.status,a.offset))
            return
        if a.command == 'tools':
            from .tools import inventory
            emit(a, inventory(a.history))
            return
        if a.command == 'opencode-sessions':
            from .opencode_sessions import discover
            emit(a, discover(a.limit, a.project, a.max_projects))
            return
        if a.command == 'config':
            emit(a, config_command(a));return
        if a.command in ('tickets', 'ticket', 'ticket-import'):
            emit(a, ticket_command(a));return
        if a.command == 'ticket-route':
            from . import config as settings
            from .routing import ticket_route
            emit(a, ticket_route(a.key, cfg=settings.load(), origin=a.url));return
        if a.command == 'sessions':
            from .loop import sessions_view
            emit(a, sessions_view(a.db));return
        if a.command == 'attach':
            attach_command(a);return
        if a.command == 'watch':
            watch_command(a);return
        if a.command == 'launchers':
            from . import config as settings
            from .launchers import catalog
            emit(a, {'launchers': catalog(settings.load()), 'execution_authorized': False});return
        if a.command == 'doctor':
            from .doctor import doctor
            result = doctor(a.db, offline=a.offline)
            emit(a, result)
            if result['status'] == 'fail':
                raise SystemExit(1)
            return
        ledger = Ledger(a.db)
        cmd = a.command
        if cmd == 'init': result = {'schema': ledger.schema_version(), 'status': 'ready', 'dispatch_enabled': False}
        elif cmd == 'status': result = ledger.status()
        elif cmd == 'detail': result = ledger.detail(a.task, a.session)
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
        elif cmd == 'links':
            from .loop import links_view
            result = links_view(ledger, a.db, a.ticket, a.limit, not a.no_live)
        elif cmd == 'work':
            from . import config as settings
            from .loop import work
            result = work(ledger, a.db, a.key, a.tool, cfg=settings.load(), origin=a.url, acknowledge=a.ack,
                          refresh=a.refresh, cwd=a.cwd, lease=a.lease, prompt=not a.no_prompt,
                          dry_run=a.dry_run, scope=a.scope, token_budget=a.token_budget)
        elif cmd == 'handback':
            from . import config as settings
            from .loop import handback
            result = handback(ledger, a.target, cfg=settings.load(), confirm=a.confirm, note=a.note)
        emit(a, result)
    except (ValueError, OSError, sqlite3.Error) as exc:
        report_error(a, exc)
        raise SystemExit(2)
    finally:
        if ledger is not None:
            ledger.close()
