# What Taskrivet learns from Bosun

Reviewed upstream commit `e630cc15dd11f460b50fa070cae7bf0afcc7c124` on 2026-10-21.
This is a source review and protocol-fixture qualification, not a live Bosun deployment.

Bosun is an MIT-licensed tmux session orchestrator with a Rust TUI and a native
Mac frontend using libghostty. The Mac frontend is already a client of a separate
`bosun serve` process. Taskrivet can cooperate with this ecosystem instead of
reimplementing every session-management feature.

## Lessons and implementation decisions

| Upstream pattern | Taskrivet decision | Current state |
| --- | --- | --- |
| tmux owns live sessions; interface can detach | Introduce a persistent terminal backend with explicit attach/detach | Planned; direct PTYs currently live in the desktop process |
| One actor serializes state-changing operations | Keep one authority per resource and serialize lifecycle changes | Ledger transactions implemented; execution authority is still local/trusted |
| Unix socket snapshot, then sequenced deltas | Observe Bosun through its protocol; retain version and provenance | One-shot snapshot adapter implemented; subscriptions planned |
| Hook status and detector status are distinct | Preserve activity source and unknowns | Implemented in Bosun snapshot projection |
| Agent turn ends without implying ticket acceptance | Show turn completion separately from accepted work | Implemented; adapter never changes ledger acceptance |
| Workspaces contain related agent/test/shell panes | Add task-linked terminal tabs; consider workspace split layouts | Tabs implemented; splits planned |
| Terminal-first focus and shortcut escape paths | Keep ordinary keys with the terminal; qualify focus behavior | Basic focus tested; advanced shortcut/TUI matrix pending |
| Isolated fake-agent test environment | Test protocol and coordination with synthetic fixtures | Implemented; no real agent or paid inference used for tests |
| Event-driven updates and idle performance budgets | Prefer push events and stop hidden-window polling | PTY push events and visibility-aware ledger polling implemented |
| Worktree lifecycle includes explicit retention decisions | Require ownership and explicit reconciliation before cleanup | No automatic worktree merge/removal implemented |

## Implemented observer

```sh
python3 -m taskrivet bosun-status --socket '/path/to/bosun.sock'
```

Obtain the path from an already installed Bosun using `bosun serve --print-socket`.
The desktop's Bosun connection view takes the same explicit path.

The observer verifies that the path is a socket owned by the current user with
no group/other permissions, then sends only a protocol-v1 `hello`. It reads one
length-prefixed JSON snapshot with a bounded deadline and a 16 MiB frame ceiling,
projects session name/display/agent/activity/source, and disconnects. It does not
start Bosun, connect to arbitrary network addresses, send `cmd`, type into a pane,
copy credentials, import tasks, or authorize execution. Configuration, paths, and
recents are omitted from the displayed projection. Observation time is not proof
that the upstream agent status itself is fresh.

Tests cover fragmented frames, incomplete and oversized frames, socket permissions,
unknown status values, protocol mismatch, and `done` remaining unaccepted. No live
Bosun binary was available during this implementation; end-to-end compatibility
with a running upstream release remains unverified.

## What should remain our responsibility

Task acceptance, context budgets and provenance, account entitlement and spending,
quality-aware routing, failure recurrence, retry policy, and the dashboard authority
contract. Terminal activity is one input to these decisions, never their substitute.

Bosun exposes auto-approval options for several tools. We should not inherit them
as defaults or infer dispatch permission from an attached session. Its screen
recognizers are useful fallback signals; they are not progress or correctness proofs.

## Reuse and attribution

This adapter is independently implemented against the documented protocol. No Bosun
source code, assets, or terminal renderer was copied. If later code reuse is chosen,
retain the applicable upstream copyright and license notices and review dependencies
separately. A protocol adapter currently avoids coupling our Python/Electron package
to Bosun's Rust build and its pinned libghostty embedding API.

Sources:
- [Project and session model](https://github.com/yetidevworks/bosun/blob/e630cc15dd11f460b50fa070cae7bf0afcc7c124/README.md)
- [Mac frontend, persistence, focus and test strategy](https://github.com/yetidevworks/bosun/blob/e630cc15dd11f460b50fa070cae7bf0afcc7c124/macos/Bosun/README.md)
- [Protocol specification](https://github.com/yetidevworks/bosun/blob/e630cc15dd11f460b50fa070cae7bf0afcc7c124/docs/protocol.md)
- [Hook status implementation](https://github.com/yetidevworks/bosun/blob/e630cc15dd11f460b50fa070cae7bf0afcc7c124/src/agent_hooks/mod.rs)
- [Upstream license](https://github.com/yetidevworks/bosun/blob/e630cc15dd11f460b50fa070cae7bf0afcc7c124/LICENSE)
