# GitHub maintenance

Taskrivet uses issues for reproducible bugs and scoped feature requests,
Discussions for questions and workflow ideas, pull requests for review, and
Releases for versioned downloads. Keep public content synthetic and
deployment-neutral; see [the privacy check](public-content-privacy.md).

## Review and checks

The issue forms ask for version, reproduction or acceptance evidence, and data
boundaries. The pull request template lists the project's actual Python and
desktop commands. `CODEOWNERS` requests maintainer review; it does not by itself
require an approval or prevent a merge.

The `tests` workflow runs Python tests on Linux and macOS and builds/tests the
desktop on macOS. Its stable `Required checks` job succeeds only when both the
Python matrix and desktop job succeed. Branch protection can require that name
without depending on the individual matrix job names. The separate
`public-content-privacy` commit status must remain required.

CodeQL analyzes Python and JavaScript/TypeScript on pull requests, main pushes,
and a weekly schedule. It uses `build-mode: none`, without installing project
dependencies or running build scripts. Dependency review checks pull request
dependency changes and fails for newly introduced high or critical known
vulnerabilities. These checks complement tests and review; they do not establish
that a release is safe or that an integration was exercised live.

All new action references use immutable upstream commit SHAs. Review updates to
the actions themselves before changing those pins. The new analysis jobs use
`pull_request`, never secret-bearing `pull_request_target` execution of candidate
code. Only CodeQL's analysis job receives `security-events: write`; dependency
review needs only `contents: read` and does not post comments.

## Dependency maintenance

Dependabot checks GitHub Actions and the desktop npm manifest weekly. Action
updates are grouped; desktop patch/minor updates are grouped while major updates
stay separate for compatibility review. Updates open pull requests and do not
auto-merge. The Python runtime is standard-library-only, so no pip runtime update
job is configured. Revisit that choice if Python dependencies are introduced.

Dependabot cannot bypass the public-content guard. Any `.github/` change requires
review and a trusted manual scan, even when it is only an action pin update.

## Changes to repository controls

Changes under `.github/`, or to the privacy checker and its tests, intentionally
fail the automatic privacy scan. After reviewing the exact candidate revision,
a maintainer runs **Public content privacy** from **main**, supplies the open PR
number, and confirms `reviewed_control_changes`. Later pushes need a fresh review
and scan. Never weaken the guard, disclose its private blocklist, or treat a
workflow run from the candidate branch as the trusted scan.

Repository settings are separate from these files. Confirm Discussions, the
dependency graph and alerts, private vulnerability reporting, and advanced
CodeQL setup in GitHub. Avoid enabling both CodeQL default setup and the advanced
workflow for the same analysis. Require new checks in branch protection only
after their first successful runs establish the correct check names.

## Release notes

`.github/release.yml` groups GitHub-generated notes by `breaking-change`,
`security`, `enhancement`, `bug`, `documentation`, and dependency/maintenance
labels; unmatched pull requests still appear under Other changes. Use
`skip-changelog` only for changes deliberately omitted from user-facing notes.

Generate notes while drafting a release, then review the exact commits and assets.
This configuration does not create tags, publish releases, or upload packages.
Check version consistency, test results, artifact checksums, and the downloaded
artifact before claiming a release works. The existing container publishing
workflow is a separate action from desktop release publication.
