# Changelog

## Unreleased

- Added a supervised ticket loop to the CLI: `tickets`, `ticket`, `ticket-import`,
  `work`, `links`, and `handback`. You pick the ticket and the agent, holds must be
  acknowledged before a launch, and nothing changes a ticket's stage, tags, or holds.
  A report is posted only with `handback --confirm`, through your own adapter, with
  readback and a stable marker against duplicates. See `docs/ticket-loop.md`.
- Added `sessions` and `attach` (replay, follow, Ctrl-] to detach) for the per-ledger
  terminal service, and a standard-library Python session service that the CLI starts
  when the desktop has not. The CLI and the desktop see the same terminals.
- Added `doctor`, `watch`, `launchers`, and `config`; a private mode-0600 config file for
  the ticket-service origin, report adapter, launchers, and folders; and
  `--format table` (or `TASKRIVET_FORMAT=table`) for readable output. JSON stays the
  default. Errors are JSON on stderr with exit status 2.
- Ledger schema 2 adds ticket bindings and report records. Existing ledgers gain the
  new tables in place, and earlier versions keep reading them.
- Added a session inspector beside every terminal. The focused pane's ledger
  record — session, task, resource scope, bounded context, checkpoints,
  failures, and event trail — is read from one local `taskrivet detail` view.
- Added `python3 -m taskrivet detail --task <id>` for a read-only task view with
  its sessions, context, checkpoints, failures, events, and resource claims.
- Added split panes, tab renaming, find in the focused pane's scrollback, and a
  command palette to the desktop terminal card. A split of a task-linked pane
  joins the existing ledger session instead of claiming a new lease.
- Added workspace screenshots captured from the real renderer against a
  synthetic bridge, with the capture script kept in `desktop/scripts`.
- Added an OpenCode session drawer to the desktop terminal card. Local OpenCode
  sessions are listed as metadata only and each one opens as its own tab that
  resumes that session in its own working folder.
- Added a terminal focus mode. One button collapses the sidebar, heading, inspector,
  status strip, and title bar so the terminal owns the window, with a
  Command-Shift-F shortcut and a remembered choice.
- Added `python3 -m taskrivet opencode-sessions` for bounded local OpenCode session
  metadata reads, and raised the session service tab limit from twelve to
  twenty-four.

This alpha still does not read OpenCode transcripts, messages, credentials, or
provider settings, and it does not write to an OpenCode session. A resumed session is
a live agent process, not an isolated copy. The session inspector shows recorded
values: reported usage is not measured cost, recorded evidence is not verified
evidence, and nothing shown there authorizes execution. The ticket loop does not
select work, claim tickets at their source, sandbox agents, or run them unattended.

## 0.3.0 — 2026-10-21

- Added durable GitHub observations, bounded incremental reconciliation, coverage
  gaps, and deterministic response categories in the CLI and desktop.
- Added explicit public-summary publication with a durable outbox, authenticated
  author checks, lost-response reconciliation, and independent readback.
- Added an optional ticket-service notes bridge using source-owned updates and
  compare-and-swap protection. Polling begins only after application launch.
- Added tagged CLI container packaging and downloadable desktop/Python artifacts.
- Added a public-safe interactive Archify architecture diagram, typed source,
  validation receipt, and visual-review evidence.
- Expanded regression coverage for deduplication, pagination gaps, failure
  visibility, uncertain delivery, and spoofed publication markers.

This alpha does not implement automatic ticket execution, universal activity
coverage, verified billing, per-issue lifecycle mirroring, automatic acceptance,
or signed/notarized desktop distribution. Existing persistent terminal behavior
and the read-only dashboard ticket preview remain available.
