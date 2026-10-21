# Contributing

Start with a focused issue or pull request describing an observable user outcome.
Use Python 3.11+ and run `python3 -m unittest discover -s tests -v`.
The core intentionally has no runtime dependencies or provider credentials.

Preserve the distinction between recommendation, permission, execution, verification,
and acceptance. Add meaningful tests for concurrency, failure recovery, and budget
boundaries when changing them. Do not add network calls or telemetry to read commands.
Do not publish real transcripts, credentials, account details, or private tickets in
fixtures. Keep examples synthetic. Document schema changes and a migration plan.

Changes to adapters must state their supported versions, permission model, usage
provenance, cancellation semantics, and unverified assumptions. Prefer a small
qualified adapter over a large list of nominal integrations.
