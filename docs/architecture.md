# Architecture and boundaries

## Coordination core

A Python library and JSON CLI use one local SQLite WAL ledger. Transactions serialize
claims. The ledger stores tasks, exact resource keys, sessions, leases, checkpoints,
content-addressed context, profile declarations, failure fingerprints, and events.
State transitions and the event recording for each transition commit together.

Tasks move from ready to running, then review or blocked. Review can be accepted,
retried, or cancelled. Blocked work can be retried or cancelled after operator
reconciliation. Expired sessions are never resurrected; a retry receives a new ID.
Reported usage remains attached to every attempt and counts against the task budget.

Resource reservations remain for running, blocked, and review tasks. This is
conservative: the operator must reconcile stale workers and unmerged work before
releasing reservations. Exact scope keys are a caller contract, not path enforcement.

Context blobs are content addressed; attachment metadata has a source, priority,
and optional expiry. A source label is asserted provenance, not fetched or verified
content. Reattaching identical content updates that task's attachment metadata.
Multiple distinct source aliases for identical content are not retained in 0.1.

The event feed has monotonic sequence numbers. Consumers retain their cursor and
must deduplicate replayed events. SQLite is for one local host; multi-host writes
and untrusted clients are outside the supported deployment model.

## Supervised ticket loop

The CLI's ticket loop binds one operator-chosen ticket revision to a local task
(schema 2 `task_sources`), records report deliveries (`handbacks`), and opens the
chosen agent through the per-ledger session service. It reads the ticket service over
loopback HTTP and writes to a ticket only through an operator-configured adapter after
confirmation. It has no admission, claim, isolation, or unattended dispatch, so it is
not the execution service proposed below. See [ticket-loop.md](ticket-loop.md).

## Proposed execution service

A future service will accept explicit work orders from one authority. Work orders
need source revision, objective, acceptance criteria, allowed resources, credentials
by reference, account identity, budget reservation, expiry, retry ceiling, and an
idempotency key. Admission and dispatch must be distinct from recommendation.

Adapters should prefer supported structured APIs or noninteractive CLI interfaces.
PTY/TUI automation requires capability-specific qualification. Model identity alone
is insufficient: the tool harness, account, environment, permissions, and version
are part of an execution profile.

The executor will supervise isolated workspaces and processes, support pause/cancel,
and return durable receipts. A failed or timed-out provider call may have incurred
cost: preserve unknown liability and reconcile before retrying. Lease fencing must
be enforced by the actual mutation gateway before claiming stale-worker protection.
A ledger cannot prevent a disconnected worker from editing files.

A dashboard adapter will remain separate from the core. One authority owns queue
admission, budgets, and acceptance. Dashboard restarts should not terminate workers;
worker crashes should not corrupt source state. Taskrivet owns its terminal backend; no external daemon or ticket-service installation is required.

## Proposed learning and efficiency

Collect accepted outcomes, rejection reasons, repair work, operator review minutes,
wall time, tokens, cost with provenance, and uncertainty. Compare routing policies
on representative task cohorts. Include overhead from context preparation, review,
retries, and failed attempts. Preserve held-out evaluations and avoid rewarding
agents for easy-task selection or self-reported completion.

Initially use explicit rules. Add calibrated task-specific performance estimates
only when samples support them. Explore alternative routes only within authorized
budgets. Never let a learning policy relax hard authorization or privacy constraints.

## Desktop alpha

The Electron desktop and direct PTY implementation are described in
[desktop.md](desktop.md). They are not the proposed durable execution service.
The [Bosun review](bosun-integration.md) records architectural lessons for our own future session service.
