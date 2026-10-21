# Changelog

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
