# Contributing to Taskrivet

Start with an observable user outcome and a small, reviewable change. The Python
coordination core intentionally has no runtime dependencies. The desktop has its
own Node dependencies and process lifecycle.

## Find a useful change

1. Read the [README](README.md), [security boundaries](SECURITY.md), and [roadmap](docs/roadmap.md).
2. Search existing issues. Use Discussions for questions and early design ideas;
   use issue forms for a reproducible bug or a scoped improvement.
3. Confirm scope and acceptance criteria before implementing a large change.
   Existing generated backlog issues are proposals, not execution authorization
   or a promise that the described behavior is missing.
4. Link the issue from your PR. Use `Fixes #123` only when the complete acceptance
   criteria are satisfied; otherwise use `Refs #123` and describe the remaining work.

## Local setup and checks

Python 3.11 or later:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

Desktop changes:

```sh
cd desktop
npm ci
npm test
npm run build:mac  # macOS / Apple Silicon packaging check
```

The repository's Actions matrix runs Python tests on Linux and macOS, plus desktop
checks. Report the commands and results you actually ran. A unit test is distinct
from a packaged-app launch or real keyboard/PTY verification. Documentation-only
changes should include link and rendering checks; do not invent a test result.

## Preserve the contracts

Keep recommendation, permission, execution, verification, and acceptance separate.
Installed executables do not establish provider entitlement, quota, health, or cost.
A finished process does not mean accepted work. No silent paid-provider fallback.

Use synthetic fixtures. Add meaningful coverage for changed concurrency, lease,
budget, identity, retry, and failure-recovery behavior. Adapters must document
supported protocol versions, permissions, freshness, cancellation, idempotency,
and unknown outcomes. Document schema migrations and compatibility.

Keep read-only operations free of hidden writes, provider inference, and telemetry.
Explicit network observation commands should document their destinations and limits.
Never expose generic shell execution through the desktop IPC bridge.

## Privacy and review

Do not commit provider credentials, private transcripts, real tickets, local
installation paths, account details, customer material, or operational screenshots.
Use generic integration names and explicitly configured origins. Review public PR
bodies, issue text, release notes, and screenshots separately from source files.

The [public-content privacy check](docs/public-content-privacy.md) inspects tracked
content using a private policy. Changes under `.github/`, or to the checker and
its tests, require a maintainer to review the exact diff and run the trusted manual
scan from `main` for that PR. Never weaken the gate or expose its private entries.

Keep commits focused. Stage only the paths you own. Explain what changed, why,
validation performed, and any limitations in the PR template. The maintainer may
ask for revisions; an open PR or successful check is not acceptance by itself.

## Releases and dependencies

Use the release's checksums and release notes when testing packaged builds. A new
release needs an intentional version, reproducible artifacts, and artifact validation;
merging code does not publish an app automatically. Dependency update PRs go through
the same checks and review as other changes. Generated release notes supplement a
maintainer's explanation of behavior and known limitations.

Participation follows our [code of conduct](CODE_OF_CONDUCT.md). Security problems
belong in [private reporting](https://github.com/hamanakam1/taskrivet/security/advisories/new).
