# Security boundaries

Taskrivet 0.3 is a trusted, single-user local coordination tool, not an authorization
server or sandbox. Anyone who can use the database can perform operator decisions.
Session IDs identify attempts; they are not authentication tokens. Do not expose the
Python API or database to untrusted clients or place the database on a shared host.

The ledger records explicit supplied context and evidence locally. It does not
redact secrets automatically. Store it outside public repositories; the default is
`~/.taskrivet/ledger.sqlite`. New storage directories use mode 0700 and the database
uses mode 0600. Existing directory permissions are not modified. Review permissions
when selecting a custom location. Use SQLite's backup API for consistent live backups.

The Python core does not execute models or shells. The desktop deliberately opens
local login shells on user request, with normal user permissions and environment.
It is not a shell sandbox or a spending firewall. Commands you type can access files,
networks, and existing credentials. See [desktop boundaries](docs/desktop.md).
The tool catalog scans executable filenames and optionally a bounded history sample.
Direct launches execute the currently detected binary with no extra arguments.
Tool names are not a trust guarantee; local wrappers and executable replacements
run with your normal permissions. Taskrivet’s own detached session service owns PTYs.
It uses a per-ledger Unix socket in a mode-0700 directory, a mode-0600 socket, and
a mode-0600 random handshake token. No TCP listener or third-party daemon is used.
Same-user processes remain within the trust boundary. Quitting the desktop does
not stop agents; use Stop terminal. The service retains at most 1 MiB of UTF-8 output
per terminal in memory, with at most 12 terminal records. Service failure or reboot
loses terminal state; do not infer completion or automatically replay commands.

Scope and budget constraints govern the ledger only; external agents must cooperate.
A blocked session does not terminate a process, and expiry must be reconciled before
retry. Electron's frontend is isolated and locally served; terminal output is not
persisted or sent to models automatically. No telemetry is implemented.

Report sensitive vulnerabilities through GitHub private vulnerability reporting if
enabled, rather than placing secrets or working exploits in public issues. If that
channel is unavailable, open a minimal issue requesting a private contact channel.

GitHub synchronization uses the existing local `gh` authentication. It never copies
credentials into an agent, artifact, or public comment. Remote titles/comments are
untrusted observations. Suggested response categories do not execute commands,
merge PRs, create tickets, change acceptance, or authorize spending. Explicit public
summary files are operator-selected publication content; they are not automatically
redacted. The dashboard bridge never exports ticket detail or terminal transcripts.
Its local configuration must be owned by the current user with mode 0600.
