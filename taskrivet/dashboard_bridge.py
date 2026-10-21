"""Optional local bridge; source-owned CAS writes and explicit public text only."""
import argparse
import json
from pathlib import Path
import sys

from .github_sync import GitHubSync

START = '[Taskrivet GitHub sync]'
END = '[/Taskrivet GitHub sync]'


def reconcile(adapter, ticket, status, published=None):
    card = adapter.read_card(ticket)
    if card is None:
        raise ValueError("Mapping target does not exist; no ticket created")
    gaps = [name for name, feed in status['coverage'].items()
            if not feed['page_complete'] or feed['error']]
    block = '\n'.join([
        START, 'Repository: ' + status['repo'],
        'Last poll: ' + str(status['last_poll']),
        'Response counts: ' + json.dumps(status['responses'], sort_keys=True),
        'Incomplete feeds: ' + (', '.join(gaps) or 'none within bounded pages'),
        'Historical coverage is incomplete; activity is review-only. No ticket status changed.',
    ])
    if published:
        block += '\nPublished summary: ' + published['url']
    notes = card.get('notes') or ''
    if notes.count(START) != notes.count(END) or notes.count(START) > 1:
        raise ValueError('Malformed existing sync block; no write')
    if START in notes:
        start, finish = notes.index(START), notes.index(END)
        if finish < start:
            raise ValueError('Malformed existing sync block; no write')
        notes = notes[:start] + notes[finish + len(END):]
    new = (notes.rstrip() + '\n\n' + block + '\n' + END).strip()
    adapter.update_notes(ticket, new, expected_revision=card['revision'])
    after = adapter.read_card(ticket)
    if after['notes'] != new or after['status'] != card['status']:
        raise ValueError('Dashboard readback mismatch; reconcile source before retry')
    return {'dashboard_readback': True, 'status_unchanged': True,
            'publication': published, 'coverage': status['coverage']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('adapter', 'repo', 'sync-db'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--ticket', type=int, required=True)
    parser.add_argument('--public-summary')
    parser.add_argument('--issue', type=int)
    parser.add_argument('--publication-key')
    parser.add_argument('--poll', action='store_true')
    args = parser.parse_args()
    if args.public_summary and (not args.issue or not args.publication_key):
        parser.error('publication requires --issue and --publication-key')
    import importlib.util
    adapter_path = Path(args.adapter)
    import os
    mode = adapter_path.lstat()
    if adapter_path.is_symlink() or mode.st_uid != os.getuid() or mode.st_mode & 0o077:
        raise ValueError('Adapter must be private and owned by you')
    spec = importlib.util.spec_from_file_location('taskrivet_local_adapter', adapter_path)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    if adapter.read_card(args.ticket) is None:
        raise ValueError('Mapping target does not exist; no ticket created')
    sync = GitHubSync(args.sync_db)
    try:
        published = sync.publish(args.repo, args.issue, args.publication_key,
                                 Path(args.public_summary).read_text()) if args.public_summary else None
        if args.poll:
            sync.poll(args.repo)
        status = sync.status(args.repo)
    finally:
        sync.close()
    print(json.dumps(reconcile(adapter, args.ticket, status, published)))


if __name__ == '__main__':
    main()
