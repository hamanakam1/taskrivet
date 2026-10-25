# Roadmap

This file describes remaining proposed work. The desktop now has embedded terminal tabs,
a task inspector, failure records, and a local CLI tool catalog. A standalone session service preserves PTYs across desktop restarts. Service-crash/reboot
recovery and automated provider dispatch remain unimplemented.

For the long-term shape, the phase-by-phase delivery order, and the decision
log behind these items, see the [long-term plan](long-term-plan.md). This file
remains the short list of what is still proposed.

1. **Qualified adapter contract.** Local fake worker first; versioned work orders,
   structured receipts, cancellation, crash recovery, replay, duplicate prevention,
   workspace isolation, and authorization checked immediately before an action.
2. **Read-only inventory.** Tool versions, authentication scope, declared versus
   verified entitlements, quota freshness, trial expiry, cost provenance. No model
   calls merely to discover inventory; no credential copying between tools.
3. **Dashboard bridge.** External task mapping, bounded imports, event cursors,
   source revisions, explicit admission, independent result verification, and
   authoritative readback. No second scheduler. The supervised ticket loop covers
   bounded imports, source revisions, and report readback; explicit admission and
   independent verification remain.
4. **Useful terminal UI.** Task and session overview, pending decisions, context
   inspection, failure drilldown, attach links, pause/cancel through the same API.
   The CLI has `links`, `sessions`, `attach`, and `watch`; pause and cancel do not exist yet.
5. **Context distribution.** Role-specific retrieval, revision invalidation,
   dependency handoffs, sensitive-content classification, tokenizer adapters,
   budget allocation, and citations. Never broadcast all transcripts to all agents.
6. **Outcome-based routing.** Capability qualification and measured per-task-class
   results, uncertainty intervals, total-cost estimates, local resource pressure,
   and explicit escalation policies. Human effort is part of the cost function.
7. **Failure intelligence.** Root-cause clustering, bounded recovery playbooks,
   recurrence alerts, and semantic off-track checks evaluated against real labels.
8. **Service hardening.** Migrations, service-failure recovery, resource controls,
   and chaos tests before unattended execution; separate PTY ownership and local
   IPC authentication are implemented.

First release acceptance: installable CLI, meaningful tests, deterministic
coordination constraints, bounded context, explicit limitations, reproducible demo,
and a public repository. No claim of token savings without comparative measurements.
