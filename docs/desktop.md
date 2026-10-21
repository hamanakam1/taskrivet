# Mac desktop alpha

Taskrivet Desktop embeds xterm.js terminals backed by node-pty and connects to the
Python coordination ledger over a narrow Electron IPC bridge. It has task creation,
task-linked terminal tabs, checkpoints, failure records, review and acceptance,
context inspection, and a searchable local tool catalog.

## Run and build

Requires macOS on Apple Silicon, Python 3.11+, and Node/npm for source development.
The packaged app includes its JavaScript runtime and Python sources, but still needs
an existing Python 3.11+ installation for the ledger. It checks common Python paths.
Terminals do not require Python. This dependency is a packaging limitation of the alpha.

```sh
cd desktop
npm ci
npm start
npm test
npm run build:mac
```

The local build is `desktop/dist/mac-arm64/Taskrivet.app`. It is unsigned and not
notarized; it is a developer build, not a signed public Mac distribution. No signing
identity is acquired and no Apple enrollment is purchased by these commands.

## Lifecycle and authority

Nothing opens a shell until the user chooses New terminal and submits its form.
The selected working folder must exist. Shells inherit the user's environment and
login startup files. They run with the user's normal permissions and are not sandboxed.
A program launched manually in a shell can incur charges; the ledger's routing policy
does not intercept manual terminal commands or enforce provider budgets.

Task-linked terminals claim a ready ledger task. The lease is renewed by a checkpoint,
not by output or a busy indicator. Expiry or budget limits block ledger progress;
they do not terminate a manually controlled shell. The inspector shows the task state.
The task's exact scope keys do not restrict filesystem access.

Closing the window hides it while shells are active. Reopen the app from the Dock or
Window menu. Quitting with active shells prompts before killing PTYs. Detached child
processes may remain and must be reconciled independently. Terminals and scrollback
are not restored after app quit or a crash. A standalone Taskrivet session service is proposed.

A shell exit does not finish or accept a task. Stop the linked terminal before
submitting its result for review, accepting, or retrying. Checkpoints and failure
records are explicit operator entries, not automated evidence verification.

## Privacy and UI boundary

All frontend assets are local. The renderer uses sandboxing, context isolation,
no Node integration, denied navigation/new windows, and a restrictive CSP. IPC
checks the originating main frame and exposes explicit operations rather than a
generic shell command API. Python is invoked with an argument vector, never a shell.

Terminal output is buffered only in memory with bounded retained history. OSC 52
clipboard writes are intercepted; hyperlinks do not automatically open external
content. Terminal programs still have the same filesystem/network access as other
programs run by the user. Do not paste secrets into recorded context or evidence.

## Verification

- Unit tests cover coordination, protocol parsing, IPC argument validation and bounds.
- Packaged Apple Silicon app was launched and visually reviewed on a Mac.
- Real embedded PTY input produced expected output in `/tmp`.
- Shell input/output remained functional after closing and reopening the window.
- Quit with an active test shell displayed the confirmation and stopped the app.
- No live AI provider/TUI compatibility  was qualified.

At initial dependency review, `npm audit --omit=dev` reported no vulnerabilities.
The build dependency chain had a moderate `sprintf-js` advisory with no patched
upstream version available. It is not in the packaged runtime dependency tree.
Do not describe this alpha as security-audited or ready for untrusted clients.
