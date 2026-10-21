# Roadmap

This file describes proposed work, not delivered capabilities.

1. **Qualified adapter contract.** Local fake worker first; versioned work orders,
   structured receipts, cancellation, crash recovery, replay, duplicate prevention,
   workspace isolation, and authorization checked immediately before an action.
2. **Read-only inventory.** Tool versions, authentication scope, declared versus
   verified entitlements, quota freshness, trial expiry, cost provenance. No model
   calls merely to discover inventory; no credential copying between tools.
3. **Dashboard bridge.** External task mapping, bounded imports, event cursors,
   source revisions, explicit admission, independent result verification, and
   authoritative readback. No second scheduler.
4. **Useful terminal UI.** Task and session overview, pending decisions, context
   inspection, failure drilldown, attach links, pause/cancel through the same API.
5. **Context distribution.** Role-specific retrieval, revision invalidation,
   dependency handoffs, sensitive-content classification, tokenizer adapters,
   budget allocation, and citations. Never broadcast all transcripts to all agents.
6. **Outcome-based routing.** Capability qualification and measured per-task-class
   results, uncertainty intervals, total-cost estimates, local resource pressure,
   and explicit escalation policies. Human effort is part of the cost function.
7. **Failure intelligence.** Root-cause clustering, bounded recovery playbooks,
   recurrence alerts, and semantic off-track checks evaluated against real labels.
8. **Durable service.** Separate worker lifecycle, migrations, backups, local IPC
   authentication, resource controls, and chaos tests before unattended execution.

First release acceptance: installable CLI, meaningful tests, deterministic
coordination constraints, bounded context, explicit limitations, reproducible demo,
and a public repository. No claim of token savings without comparative measurements.
