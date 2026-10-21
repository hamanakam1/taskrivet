# Ticket-to-outcome execution contract (proposed)

Taskrivet's primary workflow is to take eligible tickets through tool selection,
context preparation, authorized execution, verification, and review. The current
implementation provides local task records, context packets, executable discovery,
and persistent terminal sessions. Automated ticket selection and dashboard dispatch
are not implemented by this document.

## Independence and authority

The core must operate with a local queue and with interchangeable source adapters.
The local ticket-service adapter is optional. Private paths, database schemas,
provider credentials, and deployment-specific ticket conventions cannot be core dependencies.
Additional adapters can target GitHub Issues, Linear, Jira, or other queues.

For an externally managed ticket, its source owns eligibility, priority, holds,
and accepted completion. Taskrivet owns execution attempts, process sessions,
context manifests, usage observations, and evidence. One coordinator admits work:
Taskrivet may propose a candidate, but the source must atomically grant a lease.
The dashboard's no-auto, review-required, pause, and explicit-approval controls
remain authoritative. Historical access or an installed executable is not a grant.

## Adapter operations

- `capabilities`: report supported operations, schema version, and source identity.
- `listEligible(cursor, filters)`: bounded candidates with source revision, freshness,
  dependencies, acceptance criteria, priority, and execution holds.
- `claim(ticket, expectedRevision, attemptId, requestedScope)`: atomic conditional
  lease with expiry, resource scope, and explicit authority. A revision conflict
  returns to selection; it never overwrites another worker's claim.
- `renew(lease, expectedRevision)`: extend ownership only while authority is valid.
- `readContext(ticket, manifest)`: return bounded source references and scoped content.
- `publishEvidence(attemptId, sequence, evidence)`: idempotent progress and artifacts.
- `requestReview(attemptId, acceptanceEvidence)`: propose review, never silently mark Done.
- `release(lease, reason)`: release only after execution is stopped or reconciled.

Adapters need contract tests for duplicate dispatch, stale revisions, hold changes,
lease expiry, offline operation, unknown write acknowledgements, and retry safety.
A lost response must be reconciled using the attempt ID before repeating a mutation.
The eventual dashboard adapter should use a supported API rather than direct DB writes.
Its actual endpoints and permission model must be verified against current source.

## Admission and tool choice

Before launch, require a claim, sufficient context, declared acceptance checks,
compatible tool capabilities, available resource ownership, and explicit access and
cost constraints. Unknown entitlement or cost excludes automatic paid dispatch.
A user can connect existing accounts locally without exporting credentials into
prompts, logs, GitHub, or another agent's environment.

Rank qualified tool/model/account combinations using accepted outcomes on comparable
tasks, expected total effort, latency, failure/rework history, and evidence confidence.
Do not confuse cheapest tokens with cheapest accepted outcome. Cold-start rankings
must disclose uncertainty. Use rules and cached metadata for routine routing; invoke
an additional model only when its decision value justifies the overhead. Record why
a tool was chosen, alternatives rejected, and what would trigger escalation.

## Context and access

Each attempt gets an objective, acceptance tests, relevant source revisions, scope,
constraints, prior failed approaches, artifact references, and a next action. Avoid
copying full transcripts to every agent. Track provenance, expiry, byte/token bounds,
redaction, content hashes, and what each worker actually received.

Access grants specify repository/worktree, filesystem scope, network destinations,
allowed operations, credential handles, expiry, and approval requirements. A grant
must be enforced by the execution environment when isolation is claimed. Current
Taskrivet terminals run as the operator and do not provide these isolation guarantees.

## Lifecycle and failure handling

Proposed states: discovered, eligible, claimed, preparing, running, blocked,
verifying, awaiting review, accepted, cancelled. Process exit, agent turn completion,
and ticket acceptance remain distinct events. Lease expiry or revocation blocks
further dispatch; stopping a running worker requires an explicit enforceable policy.

Store stable attempt IDs, ordered events, bounded output, failure categories,
reproduction evidence, retry budgets, cooldowns, escalation reasons, and receipt
reconciliation. Preserve useful partial work on failure. Retry only with a changed
condition or approach, and retain cumulative cost and token accounting.

## Delivery order

1. Taskrivet-owned session service and reconnection (implemented separately).
2. Read-only ticket-service adapter and prerequisite preview with source freshness (implemented; no admission authority).
3. Atomic claims and scoped grants with adapter contract tests.
4. Supervised single-ticket execution, evidence return, and manual acceptance.
5. Measured routing, constrained parallel work, budgets, and bounded recovery.

Open-source users can supply their own adapter and local credentials. The public
repository contains synthetic fixtures and no private dashboard data.
