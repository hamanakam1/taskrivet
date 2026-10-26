## Problem and result

<!-- Explain the concrete problem and the resulting behavior. Link a public issue
with "Fixes #..." only if this change meets its acceptance criteria. -->

## Validation

<!-- List the commands actually run and their results. Explain any checks skipped.
Required project check: python3 -m unittest discover -s tests -v
For desktop changes: cd desktop && npm ci && npm test
For packaging changes: cd desktop && npm run build:mac
For UI changes: describe the actual app/browser check with synthetic data.
A passing build does not prove a downloaded release or a live integration works. -->

## Compatibility and boundaries

<!-- Note changed CLI/JSON contracts, ledger migrations, terminal lifecycle,
integration data flow, or recovery behavior. Write "None" if not applicable.
Keep routing eligibility, execution authorization, completion, and acceptance
distinct. Explain any new provider calls or operator decisions. -->

## Review checklist

- [ ] I read `AGENTS.md`, `CONTRIBUTING.md`, and `SECURITY.md`.
- [ ] Tests and examples use synthetic data; the diff and attachments contain no credentials, private transcripts, real tickets, or local installation paths.
- [ ] Documentation describes the behavior that is implemented and tested.
- [ ] I identified any changes under `.github/` or to the privacy checker/tests for trusted maintainer review.

<!-- Control-file changes intentionally fail the automatic public-content-privacy
check. After reviewing the exact candidate SHA, a maintainer runs Public content
privacy from main with this PR number and reviewed_control_changes=true.
See docs/public-content-privacy.md. Never paste the private blocklist into this PR. -->
