# Native Mac workspace

`macos/` is a native SwiftUI rebuild of the desktop workspace. It shows the
ticket loop, ledger tasks, and session terminals, inspects any task's ledger
record, and embeds real PTY terminals (SwiftTerm) for login shells and live
`attach` sessions. It is a parallel implementation: the Electron workspace in
`desktop/` remains the reference until the native app reaches parity.

## Scope of this first cut

Included: ticket-loop list with holds, lease countdown, and report state;
ledger task list; session-terminal list with Attach; the full task inspector
(session, checkpoints, failures, bounded context, scope claims, event trail);
terminal tabs for login shells and `taskrivet attach`; a Doctor sheet.

Deferred to later cuts (still served by `desktop/`): task creation forms,
checkpoint/failure/review forms, split panes, and the searchable tool catalog.

## Build and run

Requires macOS 14+ on Apple Silicon, a full Xcode install with its license
accepted, and a Python 3.11+ with the `taskrivet` package importable.

```sh
cd macos
swift build
swift test
scripts/build_app.sh          # writes macos/build/Taskrivet.app
```

A note on toolchains: recent SDKs implement SwiftUI's property wrappers as
compiler macros, and the Command Line Tools do not ship the SwiftUI macro
plugin. Building therefore needs the full Xcode developer directory; the build
script exports `DEVELOPER_DIR` automatically when `/Applications/Xcode.app`
exists. Accepting the Xcode license (open Xcode once, or
`sudo xcodebuild -license accept`) is a one-time operator step after each
Xcode upgrade.

The packaged app is an unsigned, ad-hoc-signed developer build with bundle
identifier `org.taskrivet.native`, so it can sit next to the Electron build
(`org.taskrivet.desktop`) during the transition. No signing identity is
acquired and no notarization is attempted.

## How it talks to the ledger

Every read is a fresh `python3 -m taskrivet --format json <view>` invocation
with an argument vector — never a shell. The interpreter is probed in order:
`TASKRIVET_PYTHON`, stock locations (`/opt/homebrew/bin/python3`,
`/usr/local/bin/python3`, `/usr/bin/python3`), then a PATH lookup, and a
candidate qualifies only if `import taskrivet` succeeds. If none qualifies the
window says so and nothing is faked.

## Lifecycle and authority

The window invokes observation CLI commands. Existing `status` and `links`
reads can reconcile expired local leases; routing reads do not open the ledger.
Work, checkpoints, reports, and acceptance run in the terminal tabs as
interactive CLI sessions the operator drives; `handback --confirm` stays a
typed confirmation, not a button.

Terminals are real PTYs via SwiftTerm. A new shell tab opens a login shell in
a folder the operator picks (nothing runs until a folder is chosen). GUI apps
receive a sparse environment, so tabs get a curated base (`HOME`, `TERM`,
`SHELL`, a stock `PATH`) plus the configured interpreter, ledger, config,
session-service directory, and Python import path when set. Run-specific task,
session, and context variables are not inherited. The login shell then sources
the user's own profile on top. Shells are not
sandboxed and programs launched in them can incur charges; the ledger's
routing policy does not intercept manual terminal commands.

Attach tabs run `taskrivet attach <terminal>`; Ctrl-] detaches and the
terminal keeps running in the session service, as with the CLI.
Switching tabs keeps their processes and scrollback alive. Closing a tab ends
its local shell or attach client; closing an attach tab leaves the underlying
session-service terminal running.

## Privacy

All reads are local process invocations. The app has no network code, no
telemetry, and no analytics. Whatever a ticket service origin is configured
in the private config is contacted only by the CLI itself, exactly as when
using the terminal directly.
