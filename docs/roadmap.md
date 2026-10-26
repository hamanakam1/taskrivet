# Roadmap

Taskrivet's next goal is qualified, source-authorized ticket execution: choose an
appropriate model and provider from current evidence, run within explicit bounds,
recover without duplicate work, and return verifiable results for source-owned review.

[Delivery board](https://github.com/users/hamanakam1/projects/1) · [Milestones](https://github.com/hamanakam1/taskrivet/milestones) · [Selected roadmap issues](https://github.com/hamanakam1/taskrivet/issues?q=is%3Aissue%20is%3Aopen%20label%3Aroadmap) · [Design discussions](https://github.com/hamanakam1/taskrivet/discussions)

## Current foundation

The alpha has persistent terminal tabs, session reconnection after desktop quit,
a task inspector, bounded context, a local tool catalog, failure records, and a
supervised single-ticket CLI loop. GitHub activity observations and confirmed
reports retain source links and delivery receipts.

Automatic source claims, verified provider selection, unattended ticket dispatch,
service-crash/reboot recovery, and automatic acceptance are not complete. The
[execution contract](ticket-execution.md) describes those boundaries; the
[long-term plan](long-term-plan.md) retains the broader design.

## Next milestone: qualified ticket execution

These are existing issue identities selected from the planning catalog. They are
proposed contracts, not declarations that work is ready or authorized. Each needs
current scope and prerequisite review before implementation. No release date is promised.

| Order | Outcome and acceptance focus | Existing issue |
| --- | --- | --- |
| 1 | **Atomic source claims.** Competing workers cannot both own a ticket; changed revisions or new holds refuse launch; an unknown claim reply is reconciled by stable attempt ID. | [#252](https://github.com/hamanakam1/taskrivet/issues/252) |
| 2 | **Lease renewal and revocation.** Renew only while source authority is valid; expire or revoke without replaying a running attempt; report unresolved process state. | [#253](https://github.com/hamanakam1/taskrivet/issues/253) |
| 3 | **Model-specific qualification.** Distinguish installed/catalogued tools from fresh generation evidence, exact provider/model identity, capability, entitlement, and quota. Unknown evidence remains unknown. | [#408](https://github.com/hamanakam1/taskrivet/issues/408) |
| 4 | **Explainable route selection.** Bind the recommendation to the ticket revision and qualified launcher; show rejected alternatives and evidence confidence; invalidate changed conditions before launch. | [#452](https://github.com/hamanakam1/taskrivet/issues/452) |
| 5 | **Cost and fallback bounds.** Explicitly allowed provider/model routes and spending limits; no automatic paid fallback from a local route; distinguish measured and declared usage. | [#454](https://github.com/hamanakam1/taskrivet/issues/454) |
| 6 | **Reviewable completion receipts.** Ordered, idempotent attempt evidence tied to scope, source revision and artifacts; replay-safe delivery and separate source acceptance. | [#551](https://github.com/hamanakam1/taskrivet/issues/551) |
| 7 | **Continuous-work controls.** Visible pause state prevents new admission; resume revalidates source authority; existing process state is reported independently of scheduling state. | [#701](https://github.com/hamanakam1/taskrivet/issues/701) |
| 8 | **Crash reconciliation.** On restart, reconcile persisted attempt identities with actual service/process state; unknown outcomes never become successful completion or an automatic rerun. | [#3](https://github.com/hamanakam1/taskrivet/issues/3) |

A synthetic end-to-end acceptance run must cover competing claims, a hold changing
during preparation, expired qualification, provider failure, pause, uncertain
launch acknowledgement, restart, receipt replay, and source review refusal. A
green unit suite alone does not qualify unattended execution on a real machine.

## Contributor experience and maintenance

The maintenance milestone covers usable documentation, reproducible bug reports,
small PRs, dependency and security checks, and truthful release notes. Releases
remain intentional: a merged PR, package build, or project-card movement does not
publish a desktop application or establish end-to-end acceptance.

Use `bug`, `enhancement`, and `documentation` for change type; `area:*` labels for
the affected subsystem; `needs-triage` for scope/readiness review; and `roadmap`
for the focused milestone. GitHub's project status describes development progress,
not permission to execute ticket work. A `good first issue` should be assigned
only after a maintainer identifies a genuinely bounded, independent contribution.

## Planning catalog

The repository contains a large generated capability catalog, including repeated
slices. Those entries preserve external identities and are not a ready queue or
proof of a missing feature. Refine one issue against current source before taking
it on. Link overlaps and prerequisites; do not bulk-close entries as completed
without evidence. The focused board intentionally starts with a small set instead
of importing every proposed slice as committed work.

Longer-term work includes workspace isolation, context retrieval and invalidation,
measured outcomes by task class, bounded recovery strategies, accessible desktop
controls, and signed distribution. Discuss changes to those priorities in
Discussions and update the relevant issue and milestone together.
