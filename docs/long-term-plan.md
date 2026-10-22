# Taskrivet — long-term plan

**Status:** living document · owner: Michael Hamanaka · last reviewed: 2026-10-22
**Applies to:** the `taskrivet` package, the Taskrivet desktop app, and the public repository.

This plan describes how Taskrivet should be built over the next several
releases, what each release must prove before the next one starts, and which
claims the project is not allowed to make yet. It is deliberately written
against the code that exists today, not against an imagined future.

The short version: **Taskrivet is a coordination core whose only output is
accepted work.** Everything below exists to make that output measurable,
reproducible, and safe to run unattended. The long-term objective, stated in
the README, is *accepted outcomes per unit of total effort* — operator time,
rework, latency, tokens, credits, and cash. Subscription utilisation is
useful only when it improves outcomes.

---

## 1. Invariants

These do not change across releases. A change to any of them is a major
version and requires an explicit decision record.

| # | Invariant | Where it lives |
|---|-----------|----------------|
| I1 | **Local-first.** No required cloud dependency. Local models and local state are the default path. | `SECURITY.md`, `docs/architecture.md` |
| I2 | **Evidence, not activity.** A finished session is not accepted work. Only an explicit `accept` records acceptance. | `taskrivet/core.py` (`decide`) |
| I3 | **Eligible is not authorized.** Routing may rank candidates; it never grants execution, spend, or access. | `core.route` returns `execution_authorized: False` |
| I4 | **Declared is not verified.** A profile declaration is not proof of entitlement, authentication, health, quota, or cost. | `core.route` reasons list, `SECURITY.md` |
| I5 | **Bounded context.** Context is content-addressed, prioritised, expiring, and byte-bounded. It is reference material, never authority. | `core.pack`, `docs/architecture.md` |
| I6 | **No silent rewriting of the goal.** Context, evidence, and remote observations cannot change an objective or acceptance criterion. | `docs/ticket-execution.md` |
| I7 | **No unmeasured claims.** No savings, throughput, or quality number is published without a reproducible measurement behind it. | `README.md`, `docs/roadmap.md` |
| I8 | **Local inventory stays local.** Tool discovery output contains private installation paths and is never committed or published. | `AGENTS.md`, `SECURITY.md` |
| I9 | **No credentials leave the host.** Taskrivet never copies provider credentials into prompts, logs, artifacts, GitHub, or another agent's environment. | `SECURITY.md`, `docs/ticket-execution.md` |
| I10 | **Fail safe.** Every autonomous path has a hard limit and a human-escalation exit. | `docs/roadmap.md`, `docs/ticket-execution.md` |

---

## 2. Where the project actually is (v0.3, 2026-10-21)

Verified against the current tree, not the roadmap text.

**Real and working today**

- A single SQLite WAL ledger (`taskrivet/core.py`) holding tasks, sessions with
  leases, checkpoints, content-addressed context, profile declarations,
  failure fingerprints, and a monotonic event feed. State transitions and their
  events commit in the same transaction.
- A JSON-first CLI (`taskrivet/cli.py`): `init`, `status`, `task-add`, `start`,
  `checkpoint`, `fail`, `finish`, `accept` / `retry` / `cancel`, `context-add`,
  `pack`, `profile-add`, `route`, `events`, `tools`, `dashboard-preview`,
  `github-poll` / `github-status` / `github-cycle`.
- Conflict control: one active session per task, exact resource-key overlap
  detection, lease expiry, a stagnation heuristic (three identical-evidence
  checkpoints block progress), and per-task token budgets that count across
  retries.
- Bounded context packing: mandatory content never silently truncated,
  deduplication by SHA-256, priority order, expiry and oversize omissions
  reported in diagnostics, `--packet-only` emitting a compact byte-budgeted
  packet.
- A local, rule-based eligibility router that filters by task kind, declared
  context capacity, cost class, and declaration freshness, and deliberately
  returns **unranked** options until outcome evidence exists.
- A read-only ticket-service preview (`taskrivet/dashboard.py`): GET-only,
  local-origin-only, no redirects, no proxy, 8 MiB cap, 10 s timeout,
  `execution_authorized: False` on every row, and explicit reasons for each
  ineligibility.
- Durable GitHub observation and reconciliation with a public-summary outbox,
  authenticated author checks, lost-response reconciliation, and independent
  readback (`taskrivet/github_sync.py`).
- A local tool catalogue that discovers executables from PATH and common
  install locations, with 26 coding-agent command-name profiles, plus an
  explicitly-invoked bounded history scan.
- A Mac desktop alpha (`desktop/`) on Electron + node-pty with real embedded
  terminals, task-linked tabs, an inspector, a failure ledger, and a detached
  session service that owns PTYs and survives a window or app quit.
- A public-content privacy guard (`scripts/public_content_guard.py`) that
  inspects Git objects as data and blocks blocklisted content from public
  branches.

**Not implemented, and must not be implied**

- Automatic ticket execution, automatic acceptance, and autonomous dispatch.
- Verified billing, quota, or entitlement checks. Cost is operator-declared.
- Per-issue lifecycle mirroring and universal activity coverage.
- Process isolation or sandboxing. Terminals run as the operator.
- Service-failure and reboot recovery for terminals.
- Any measured savings, throughput, or quality advantage.
- Signed or notarised desktop distribution.

**The structural gap that shapes the whole plan:** the desktop owns process
lifecycle while the ledger owns task lifecycle, and the two are joined only by
a lease. A lease is a bookkeeping fact, not a fence. The ledger cannot stop a
disconnected worker from editing files, and a worker cannot prove to the
ledger that its edits are the ones that were reviewed. Every later phase
exists to close that gap.

---

## 3. Target shape

Taskrivet grows into five layers. Each phase below adds or hardens one of them.

```
┌───────────────────────────────────────────────────────────────┐
│ 5  Presentation      desktop app, CLI, public adapters       │
├───────────────────────────────────────────────────────────────┤
│ 4  Authority         one coordinator: admission, grants,      │
│                       acceptance, escalation                  │
├───────────────────────────────────────────────────────────────┤
│ 3  Execution         supervised workers, isolated workspaces, │
│                       scoped access, durable receipts         │
├───────────────────────────────────────────────────────────────┤
│ 2  Coordination core ledger, leases, events, context,        │
│                       outcomes            (ships today)       │
├───────────────────────────────────────────────────────────────┤
│ 1  Evidence          immutable audit trail, receipts,        │
│                       provenance, verification results        │
└───────────────────────────────────────────────────────────────┘
```

Layer 2 is close to done. Layers 1, 3, 4, and 5 are where the work is.

---

## 4. Delivery phases

Each phase lists what must exist, what must be true, and what must **not** be
claimed when it closes. A phase that cannot demonstrate its exit criteria is
not finished, regardless of how much of the list is checked off.

### Phase 0 — One authority, one attempt record (0.3 → 0.4)

*Make the ledger the only source of truth about work.*

Build

- Ledger schema v2 with an explicit `attempts` table: stable attempt ID,
  task, tool profile, environment fingerprint, started/ended timestamps,
  outcome, receipt references, and cumulative cost/token accounting that
  survives retries.
- Lease fencing tokens: a claim issues a monotonically increasing token; the
  mutation gateway rejects writes carrying a stale token. This is the first
  place the ledger stops being advisory.
- A durable `receipts` table for every externally-visible action (claim,
  publish evidence, request review, release) with an idempotency key, so a
  lost response is reconciled by attempt ID instead of repeated.
- Event feed v2: every event carries a source revision, an attempt ID, and a
  stable cursor contract. Adapters must deduplicate on replay.
- Session service v2: the service reports attempt state into the ledger, so a
  terminal that dies is visible in the ledger rather than only in a window.
- Adapter contract test harness: duplicate dispatch, stale revision, hold
  change, lease expiry, offline operation, unknown write acknowledgement, and
  retry safety, run against every adapter implementation.

Exit criteria

- A crash of the desktop leaves the ledger able to describe every attempt that
  ever existed, with no orphan state and no silent completion.
- Two coordinators cannot both hold an active claim on one task.
- The contract suite runs in CI and passes for the in-tree adapters.

Not claimable yet: that any work completed autonomously, or that a fence
prevents a stale worker from writing files.

### Phase 1 — Qualified execution (0.4 → 0.5)

*Make it possible to run work without an operator watching every keystroke.*

Build

- **Execution profile v2.** A profile is not a name; it is tool + account +
  environment + version + declared entitlement + freshness window, with each
  field separately attestable. `core.route` gains a schema migration so a
  v1 declaration reads as *incomplete*, not as *eligible*.
- **Scoped access grants.** A grant names the repository or worktree, the
  filesystem scope, network destinations, allowed operations, credential
  handles, expiry, and approval requirements. Grants are enforced by the
  execution environment. If enforcement cannot be demonstrated, the grant is
  not issued — the ledger records the request and the refusal.
- **Supervised single-ticket execution.** One ticket, one worker, one
  worktree, durable receipts, explicit pause and cancel, and bounded output
  capture that matches the service's current 1 MiB bound.
- **Operator acceptance stays explicit.** Every path still ends in a human
  `accept`. Automation may *propose* acceptance with evidence attached; it
  may not record it.

Exit criteria

- A demonstration where a ticket is claimed, executed, evidenced, and
  accepted with a human reviewing the evidence trail.
- A demonstration where the grant was refused because the environment could
  not enforce it.

Not claimable yet: verified billing, verified quota, or that any provider
account was healthy at dispatch time.

### Phase 2 — Measured routing (0.5 → 0.6)

*Replace unranked options with measured choices, honestly.*

Build

- **Outcome capture.** Every attempt records: accepted or rejected, rejection
  reason code, repair work, operator review minutes, wall time, reported
  tokens, and cash cost *with provenance* (declared, measured, or unknown).
  Unknown stays unknown.
- **Task cohorts.** A cohort is a labelled set of comparable tasks with
  held-out evaluation. Routing policies are compared offline on cohorts, never
  online on live work.
- **Rule-based ranking v1.** Rank by measured accepted outcomes per unit of
  total effort within a cohort, with an explicit uncertainty interval and an
  explicit escalation rule for cold-start cases. No model-generated quality
  estimate enters the ranking.
- **A measurement harness** that produces the baseline first. Until the
  baseline exists, savings remain `null` — exactly as `core.status` reports
  today.

Exit criteria

- A published comparison on a representative cohort, with the baseline, the
  candidate policy, the sample size, and the uncertainty stated.
- Routing still refuses to rank a task class it has no evidence for.

Not claimable yet: any savings figure. A number without a baseline and a
reproducible harness is a marketing claim, not a measurement.

### Phase 3 — Bounded parallelism and recovery (0.6 → 0.7)

*Let more than one thing run at once, safely, and recover from failure.*

Build

- **Resource reservation that is enforced.** Worktree-per-attempt isolation,
  a global concurrency budget, and a per-scope reservation that the runtime
  actually refuses to violate — not a note in the ledger.
- **Failure intelligence.** Root-cause clustering over the existing failure
  fingerprints, bounded recovery playbooks, recurrence alerts, and
  semantic off-track checks evaluated against real labels.
- **Service durability.** Crash recovery for the session service, explicit
  reboot behaviour (decided, not accidental), migrations for the ledger
  schema, resource controls, and chaos tests before any unattended run.
- **Repair economics.** Attempt cost is preserved across retries; a retry
  requires a changed condition, and cumulative spend stays attached to the
  task.

Exit criteria

- A chaos test where the service is killed mid-attempt and the system
  reconciles to a known state without guessing completion.
- A parallelism demonstration where two attempts ran concurrently and
  neither could touch the other's scope.

Not claimable yet: that the system can run unattended for a long period, or
that failures are solved rather than merely recorded.

### Phase 4 — Open release (0.7 → 1.0)

*Make it usable by someone else without the author in the room.*

Build

- **Adapter SDK.** A documented adapter interface (`capabilities`,
  `listEligible`, `claim`, `renew`, `readContext`, `publishEvidence`,
  `requestReview`, `release`) with a published contract suite that third
  parties can run against their own implementation.
- **Signed distribution.** Notarised Mac build, `pip install taskrivet`,
  `npm install taskrivet-desktop`, and a container image that is clearly
  labelled as the CLI, not the app.
- **Stable schemas.** A versioned CLI output contract and event contract, with
  a documented compatibility window.
- **A published benchmark** with a reproducible harness, a stated baseline, and
  honest error bars.
- **Operator documentation for failure.** What to do when a lease expires, a
  receipt is lost, a service dies, or a grant is refused.

Exit criteria

- A third party can install, run the contract suite, and contribute an
  adapter without asking the author a question.
- The public repository passes its own privacy guard on every branch.

Not claimable yet: that Taskrivet is the best way to coordinate agents. It is
one way, with published evidence.

---

## 5. Cross-cutting workstreams

These run alongside the phases, not after them.

**Security model.** The current trust boundary is "single trusted operator on
one host". That boundary is stated in `SECURITY.md` and must stay true until a
real boundary exists. Untrusted clients are out of scope until (a) the IPC
bridge carries per-caller authentication, (b) the session socket's handshake
is enforced against a non-owner process, and (c) the execution environment can
demonstrate enforcement of a scope grant. Each of those is a Phase 1 item;
until they land, the answer to "can I expose this?" stays no.

**Privacy.** The public-content guard blocks blocklisted terms in tracked
files. Two additions are needed as the repository grows: the blocklist should
cover private *paths* and *identifiers*, not only secrets, and the guard
should also cover image and binary attachments, which it currently does not.

**Packaging.** The desktop currently needs an external Python 3.11+ install.
The 1.0 packaging target is a self-contained runtime, or a clearly documented
and clearly stated dependency, with the CLI container as the primary
distribution for server-side use.

**Documentation.** The interactive system guide (`docs/index.html`) is the
public explainer and must be regenerated whenever the architecture moves. The
CLI reference, the event contract, and the adapter contract are versioned
alongside the code that implements them.

**Observability, carefully.** No telemetry ships. Local-only export of
attempt telemetry is acceptable when it is operator-initiated, redacted by
default, and never includes transcript content.

---

## 6. Metrics that decide whether this is working

Reported as a small, honest set. Each is measurable from the ledger; none
requires a model.

| Metric | Definition | Why it matters |
|--------|-----------|----------------|
| Accepted outcomes per operator hour | accepted tasks ÷ operator minutes spent, including review | The stated long-term objective |
| Rework rate | accepted tasks that required ≥1 retry ÷ accepted tasks | Is the context and routing good enough? |
| Context efficiency | context bytes delivered per accepted outcome | Does less repeated context actually hold? |
| Failure recurrence | distinct failure fingerprints per accepted task | Is the system learning or looping? |
| Escalation rate | attempts that ended in human escalation ÷ attempts | Is the guardrail too tight or too loose? |
| Measurement honesty | number of published numbers without a baseline | A project that cannot count this cannot be trusted |

A number that cannot be produced from the ledger stays `null` in the product
surface, as `measured_cash_cost` and `measured_token_savings` do today.

---

## 7. Risks

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Scope creep into an agent framework | Loses the coordination focus entirely | Invariant I2 and the phase exit criteria; new features must name the metric they move |
| Author bus factor | The plan stalls at any single point | Contract suites and adapter SDK land before the first long unattended run |
| Local-only ceiling | Cannot serve a team or a fleet | Deliberate. Multi-user is a Phase 4+ product decision, not a Phase 1 feature |
| Provider API drift | Routing, quotas, and cost assumptions rot | Profile freshness windows, `verified_until` expiry, and declared-vs-verified separation already in place |
| Privacy guard false positives | Blocks legitimate releases | Maintainer-reviewed manual scan path, already present; keep the escape hatch narrow |
| Guardrail erosion | "Fail-safe" quietly becomes "fail-open" | The escalation path is a first-class test case, not a branch that is rarely run |
| Measurement theatre | Savings claims without baselines | I7, plus a published harness before any number is stated |

---

## 8. Explicit non-goals

Taskrivet is not, and will not become:

- an agent framework, a model host, or a prompt-construction library;
- a replacement for tmux, a terminal emulator, or an IDE;
- a cloud service, a hosted dashboard, or a multi-tenant product;
- a spending firewall — the ledger constrains Taskrivet's own bookkeeping,
  not a manually launched shell;
- a ticket system — it consumes tickets from whoever owns them;
- a source of truth for a worker's own progress — the worker and the operator
  supply evidence, Taskrivet records it.

---

## 9. Decision log

Decisions taken in this plan, with the reason each one was made.

| # | Decision | Reason |
|---|----------|--------|
| D1 | Keep the coordination core standard-library-only | The core is the thing that must keep working; dependencies become failure modes |
| D2 | Make the ledger the authority, not the desktop | The window is disposable; the record is not |
| D3 | Introduce fencing tokens before parallel work | Parallel work without fencing is corruption with extra steps |
| D4 | Keep routing unranked until a baseline exists | A ranking without evidence is a guess with a confidence score attached |
| D5 | Require human acceptance at every path, including automated ones | Acceptance is the product's only output; automating it automates the definition of success |
| D6 | Enforce grants only where enforcement is demonstrable | A grant that is merely recorded teaches the operator the wrong thing |
| D7 | Build the adapter SDK before third-party adapters exist | The contract is easier to change before it has users |
| D8 | Publish numbers only with a harness | See I7 and the measurement-theatre risk |
| D9 | Ship no telemetry, ever, by default | Local-first is the product, not a deployment option |
| D10 | Keep the desktop optional and the CLI first | The CLI is the interface that survives UI churn and works over SSH |

---

## 10. Open questions

These need an owner's answer before the next phase starts.

1. **Who is the first non-author user?** The 1.0 adapter SDK is designed for
   someone who is not the author. If that person does not exist yet, Phase 4
   should be scoped down to a single adapter with a real consumer.
2. **Is the ticket service optional or central?** Today it is optional. If it
   becomes central, admission authority moves with it, and that is a larger
   change than any item in Phase 1.
3. **What is the acceptable unattended window?** Phase 3's chaos testing and
   Phase 4's "run it overnight" both depend on a number — minutes, hours, or
   days — that is a risk decision, not a technical one.
4. **Does `intent_coverage` in the downstream verifier stay?** Taskrivet's
   context and the verifier's semantic diff measure overlapping but different
   things. They should agree on one vocabulary before either is trusted as a
   gate.

---

## 11. Keeping this document honest

- This plan is updated in the same commit as the change it describes, never
  separately.
- A phase is closed by evidence in the repository, not by a checklist.
- If a phase's exit criteria cannot be met, the phase stays open and the
  roadmap says so.
- `docs/roadmap.md` remains the short list of remaining proposed work; this
  document is the long-term shape. When they disagree, this document explains
  *why*, and the discrepancy is fixed in the same commit.

## See also

- [Architecture and boundaries](architecture.md)
- [Roadmap](roadmap.md)
- [Ticket-to-outcome execution contract](ticket-execution.md)
- [Desktop alpha](desktop.md)
- [Security boundaries](../SECURITY.md)
