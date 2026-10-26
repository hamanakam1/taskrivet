# Changelog

## 0.5.1 — 2026-10-26

- Introduce the riveted-R identity with editable light, dark and monochrome logos,
  app artwork, browser icons, and a repository/link preview image.
- Use the same icon in Electron and native macOS packages, and matching marks in
  the desktop sidebar, project README and website.
- Include a reproducible asset generator, pinned open-font source and license,
  usage guide, small-size review sheet, and asset checksum manifest.

This is a branding-only preview update to 0.5.0. The native workspace remains a
developer preview, and neither desktop is notarized. Execution, routing and
acceptance behavior is unchanged.

## 0.5.0 — 2026-10-25

This is a preview release of the merged routing and execution-request foundation.

- Add source-bound routing observations to the CLI and native workspace. Stale,
  unavailable and unqualified evidence remains visible without selecting a model
  or granting dispatch authority.
- Add an explicit source-owner execution client with a private durable journal,
  exact source/card/control/route binding, one POST per intent, and reconciliation
  after lost acknowledgements or restart. Bounded observation follows one request;
  it does not admit additional tickets or mark source work accepted.
- Preserve the supported local-inference policy: paid and unknown-entitlement
  routes are refused. A separately installed and configured owner must retain its
  readiness, approval, claim, pause and independent acceptance gates.
- Fix native terminal environment encoding, retain open terminals across tab
  switches, and set working directories on child processes only. An unchecked
  Electron context-inheritance option now opens a standalone terminal.
- Read session handshake tokens through one validated file descriptor and include
  the shared helper in desktop packages.
- Strip debug metadata from the packaged native executable and Electron terminal
  helpers before signing and archiving, so release downloads do not retain
  absolute build-machine paths.
- Add contributor guides, structured issue forms, roadmap/project support,
  dependency review, CodeQL, and grouped dependency updates. Avoid duplicate PR
  builds and cancel superseded native CI runs.
- Align CLI, Python package and Electron version metadata, including the CLI
  version correction previously published in 0.4.0.

The native workspace remains a developer preview; visual interaction qualification
is incomplete. Neither desktop is notarized. Owner installation and live ticket
qualification, continuous admission, measured quality/latency ranking, and a
paid-provider budget remain separate work. No live service is activated by this
release. See `docs/owner-execution.md`, `docs/routing.md`, and `docs/macos.md`.

## 0.4.0 — 2026-10-25

- Correct the CLI package version to match the release metadata.

- Add a native SwiftUI Mac workspace under macos/: ticket loop, task inspector,
  session attach, and embedded PTY terminals via SwiftTerm, with ledger reads
  through CLI JSON. Observation commands may reconcile expired local leases;
  interactive operator terminals retain the work/report/acceptance controls.
- Reserve room for the handback marker line inside the 4,000-byte report budget,
  so a ticket service that caps the whole note cannot cut the marker off.
- Record the run folder in the `agent.launched` event and the `links` view.

## 0.3.2 — 2026-10-24

- Add ticket-aware terminal badges with friendly objective labels and explicit standalone state.
- Add explicit active-ticket context inheritance for CLI launches through shared ledger sessions.
- Show shared-session counts and distinguish owner versus joined terminal bindings.

## 0.3.1 — 2026-10-24

- Add the supervised ticket loop and shared local session service to the desktop alpha.
- Keep ticket selection, execution authorization, handback, and acceptance as separate gates.
- Publish the Apple Silicon desktop package and Python CLI artifacts from the verified release commit.

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
