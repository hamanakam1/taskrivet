# GitHub synchronization

Version 0.3 adds durable observation and explicit summary publication. It does not
promise every historical GitHub event or mirror every issue into the dashboard.

## Inbound observations

```sh
python3 -m taskrivet github-poll --repo owner/repository
python3 -m taskrivet github-status --repo owner/repository
```

Requires an authenticated `gh` on PATH. Uses the existing account and permissions.
The SQLite store defaults to `~/.taskrivet/github.sqlite`, with private permissions.
Each observation has repository, source kind, stable identity, revision hash,
short title, suggested response, URL, and receipt time. Full comment bodies are
not persisted. Repeated observations deduplicate; changed revisions remain visible.

| Source | Suggested response |
| --- | --- |
| Issues | Reconcile ticket change |
| Issue comments | Review external feedback |
| PRs, review comments, commits | Review code change |
| Failed workflow runs | Investigate failed check |
| Releases | Verify release artifacts |
| Other events | Inspect repository activity |

These are deterministic review categories, not autonomous decisions or executions.
Counts are cumulative observations, not counts of unresolved incidents. External
contributions never authorize a command, access grant, merge, ticket, or spend.

Polling uses bounded pages. Incremental feeds overlap by five minutes; a cursor
advances only after that feed completes. Failed and truncated feeds remain visible.
GitHub's Events API is capped at 300 events and may be delayed. It cannot establish
complete history. Deletions, transient changes between polls, discussions, detailed
reviews, check suites, deployments, security alerts, and audit-log events are not
completely covered. A webhook inbox plus source-specific reconciliation is future
work. The UI always reports `all_activity_guaranteed: false`.

## Optional ticket-service mapping

Create a private JSON file at `~/.taskrivet/github-bridge.json`:

```json
{
  "enabled": true,
  "repo": "owner/repository",
  "sync_db": "/absolute/private/github.sqlite",
  "adapter": "/absolute/private/ticket_adapter.py",
  "ticket": 123
}
```

```sh
chmod 600 ~/.taskrivet/github-bridge.json
python3 -m taskrivet github-cycle --config ~/.taskrivet/github-bridge.json
```

The ticket must already exist. A private, trusted Python adapter supplies
`read_card(ticket)` returning `notes`, `status`, and an opaque `revision`, plus
`update_notes(ticket, notes, expected_revision=...)`. The adapter must use the
source-owned API, enforce compare-and-swap, and raise on conflicts. It is trusted
local code, not a downloaded GitHub contribution. Set its mode to 0600. The bridge
updates only its delimited notes block and independently reads back the result.
Existing notes, source ownership, status, and execution holds remain authoritative.
A missing target, concurrent conflict, or malformed/oversized note blocks the write.
No direct database writes or automatic ticket creation occur.

The desktop starts this cycle on app launch and every five minutes while open.
Quit stops its timer; closing a window on macOS leaves the app running. A lock
prevents overlapping cycles. `github-bridge.receipt.json` records the latest cycle
and whether dashboard readback succeeded. Set `enabled` to false to disable it.
The bridge is optional: standalone users do not need ticket-service or its modules.

This mapping writes a repository-level digest into one explicitly selected ticket.
It does not create a dashboard card for every issue, overwrite issue titles/status,
or claim conflict-free bidirectional lifecycle synchronization.

## Explicit outbound summary

Create a file containing only the information intended for publication, then run:

```sh
python3 -m taskrivet.dashboard_bridge \
  --adapter /absolute/private/ticket_adapter.py \
  --ticket 123 --repo owner/repository \
  --sync-db ~/.taskrivet/github.sqlite \
  --issue 42 --publication-key validation-2026-10-21 \
  --public-summary ./public-summary.md
```

The publisher binds the key to the issue and content hash, reserves it durably,
checks existing comments, sends once, and verifies the resulting comment. Matching
receipts must have the exact body and the authenticated account as author. If the
response is lost, a retry reconciles an existing comment without sending again.
An uncertain send with no matching receipt stops; do not use a new key simply to
bypass uncertainty. Review the issue and outbox before deciding how to recover.
An edited/deleted comment is not automatically recreated. Confirmed receipts record
past publication; they are not a guarantee the comment remains unchanged forever.

GitHub may throttle content creation independently of reads. A zero exit status
from a wrapper is insufficient publication evidence: require an independent URL
and content readback. Respect rate-limit cooldowns rather than repeated writes.
The bridge exports only the supplied public file, never dashboard details, account
credentials, private paths, terminal history, or transcripts automatically.

## Distribution

A version tag runs the container workflow, which tests the Python core, builds and
smoke-tests the image, then publishes the versioned CLI package to GHCR. The image
contains no desktop, agent binaries, `gh`, or dashboard modules. Release assets
include a separately built unsigned macOS arm64 application and Python wheel/sdist.
The app requires Python 3.11+; the desktop is not yet signed or notarized. Verify
SHA-256 checksums before installing downloaded artifacts. Source builds remain
available. PyPI and npm publication are not configured.
