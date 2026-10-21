# Taskrivet

```text
TTTTT  AAA   SSSS K   K RRRR  IIIII V   V EEEEE TTTTT
  T   A   A S     K  K  R   R   I   V   V E       T
  T   AAAAA  SSS  KKK   RRRR    I   V   V EEEE    T
  T   A   A     S K  K  R  R    I    V V  E       T
  T   A   A SSSS  K   K R   R IIIII   V   EEEEE   T

  >_ Less repeated context. More accepted work.
```

**Less repeated context. More accepted work. Visible failures.**

Taskrivet is an open-source, local-first coordination core for people working
across AI coding agents, CLIs, and terminal sessions. Give each session a clear
objective, a bounded context packet, an explicit owner, and an evidence trail.
Measure useful outcomes instead of how many agents are busy.

**Status: v0.2 desktop alpha.** A Mac app with real embedded terminal tabs,
plus a working coordination ledger and JSON CLI. Create tasks, record checkpoints,
inspect bounded context, track recurring failures, and read existing Bosun session
activity. Terminal commands are controlled by you; automated model dispatch,
restart-proof terminals, verified billing, and ai-dashboard integration are future work.

## Mac desktop app

```sh
cd desktop
npm ci
npm start
```

Requires Python 3.11+ for the ledger and Node/npm for source development.
`npm run build:mac` builds an unsigned Apple Silicon `.app` locally. The desktop
has runtime dependencies; the Python coordination core remains standard-library-only.
See [desktop setup and lifecycle](docs/desktop.md). Closing a window keeps active
shells in the app process; quitting the app does not preserve them.

## Bosun integration

[What we learned from Bosun](docs/bosun-integration.md) explains the architecture
and the implemented read-only adapter. It reads a protocol-v1 snapshot from an
existing local daemon, preserves hook/detector provenance, and never treats an
agent turn ending as an accepted task. It does not launch or control Bosun.

```sh
python3 -m taskrivet bosun-status --socket '/path/to/bosun.sock'
```

## Quick start

Python 3.11 or newer. Run directly from the checkout without installing anything:

```sh
git clone https://github.com/hamanakam1/taskrivet.git
cd taskrivet
python3 -m taskrivet --help
export TASKRIVET_DB="$PWD/.taskrivet/demo.sqlite"
python3 -m taskrivet init
python3 -m taskrivet task-add demo \
  --objective 'Fix the empty search result state' \
  --acceptance 'Empty search shows useful guidance; regression check passes' \
  --scope demo-repo/search --token-budget 8000
python3 -m taskrivet profile-add local-coder --kind code \
  --context-limit 16000 --cost zero_incremental --ttl 3600
python3 -m taskrivet route demo
python3 -m taskrivet start demo --owner terminal-1
```

Copy the returned session ID into `SESSION_ID` below. Work in your agent tool,
then report a checkpoint using cumulative usage for this session:

```sh
SESSION_ID=replace_with_returned_session_id
python3 -m taskrivet checkpoint "$SESSION_ID" \
  --summary 'Added empty-state rendering' \
  --evidence 'Diff abc123; regression test passed' \
  --next 'Review the diff against acceptance criteria' --tokens 1200
python3 -m taskrivet finish "$SESSION_ID" --evidence 'Reviewable diff abc123 and test output'
python3 -m taskrivet accept demo --reason 'Operator reviewed the diff and acceptance evidence'
python3 -m taskrivet status
```

`finish` requests review. Only a separate `accept` operation marks accepted work.
Evidence and token counts are user-supplied records, not independently verified facts.
For an installed command, use a virtual environment and `python -m pip install -e .`.

## Bounded context and handoffs

```sh
python3 -m taskrivet context-add demo --file ./README.md \
  --source 'repository README at a known revision' --priority 10 --ttl 3600
python3 -m taskrivet pack demo --max-bytes 12000
python3 -m taskrivet pack demo --max-bytes 12000 --packet-only
```

The packet always includes the objective, acceptance criteria, resource scope,
status, token budget, and latest checkpoint. Content is deduplicated by SHA-256.
Higher-priority items are included first; expired and oversized items are omitted
with reasons in the diagnostics. Mandatory content never gets silently truncated.
`--packet-only` emits compact UTF-8 JSON within the exact byte budget. Diagnostics
are outside that budget. Byte counts are not tokenizer measurements.

Context is untrusted reference material, never permission to change the goal,
spend money, execute instructions, or expand access. Keep secrets out of packets.

## Coordination and failure tracking

- SQLite transactions prevent two ledger sessions from claiming the same task.
- Exact resource keys prevent overlapping claims. Use the same key for a shared
  resource; directory nesting is not automatically inferred.
- A lease makes stale ownership visible. Expiry blocks the task and retains its
  resource reservation until an operator reconciles it.
- Checkpoints renew the lease, preserve a next step, and report cumulative tokens.
- Three consecutive checkpoints with identical evidence block further ledger
  progress. This is a repetition heuristic, not semantic drift detection.
- Reported token consumption accumulates across retries. Reaching the task limit
  blocks further ledger progress; it cannot stop an external process.
- Failures have categories and stable fingerprints; status groups recurrences.
- `retry` requires a reason. It does not clear usage or failure history.
- `events --after SEQUENCE` gives adapters an ordered incremental event feed.

```sh
python3 -m taskrivet fail "$SESSION_ID" --category tool_error --summary 'Compiler unavailable'
python3 -m taskrivet retry demo --reason 'Old worker stopped; compiler installed and checked'
```

Those commands illustrate the failure path for an active session, not a continuation
of the already accepted quick-start task. `cancel` applies to ready, blocked, or
review tasks after reconciliation. The desktop can stop its own terminal after confirmation; the CLI does not control processes.

## Model and tool routing

Profiles represent a tool/model/account/environment combination. The initial
router filters declarations by task kind, context capacity, freshness, and
zero-incremental-cost classification. Paid and unknown-cost profiles are excluded.
Eligible profiles remain unranked: Taskrivet does not invent quality estimates.
A declaration is not proof of entitlement, authentication, health, or available
quota, and an eligible result is never execution authorization.

The long-term objective is **accepted outcomes per unit of total effort**:
operator time, rework, latency, tokens, credits, and cash. Subscription utilization
is useful only when it improves outcomes. Savings remain unknown until measured
against a representative baseline.

## Independence and integration

Taskrivet owns its repository, package, and local database. It has no dependency
on ai-dashboard. A dashboard can become an authority and user interface through
a future adapter; external ticket IDs should map to Taskrivet task IDs.
The CLI, Python `Ledger` API, and read-only Bosun observer are the current integration surfaces.

See [architecture](docs/architecture.md), [roadmap](docs/roadmap.md),
[security boundaries](SECURITY.md), and [contributing](CONTRIBUTING.md).

## Development

```sh
python3 -m unittest discover -s tests -v
```

MIT licensed. The name describes work held together across tools and sessions.
Exact-name web/GitHub searches found no matches before creation; PyPI and npm
returned no package on 2026-10-21. These checks do not establish trademark clearance
or universal name exclusivity. Neither package registry has been published to.
