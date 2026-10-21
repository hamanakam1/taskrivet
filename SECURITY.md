# Security boundaries

Taskrivet 0.2 is a trusted, single-user local coordination tool, not an authorization
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
run with your normal permissions. No external session daemon is used.

Scope and budget constraints govern the ledger only; external agents must cooperate.
A blocked session does not terminate a process, and expiry must be reconciled before
retry. Electron's frontend is isolated and locally served; terminal output is not
persisted or sent to models automatically. No telemetry is implemented.

Report sensitive vulnerabilities through GitHub private vulnerability reporting if
enabled, rather than placing secrets or working exploits in public issues. If that
channel is unavailable, open a minimal issue requesting a private contact channel.
