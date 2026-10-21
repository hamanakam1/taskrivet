# Security boundaries

Tessivolt 0.1 is a trusted, single-user local coordination tool, not an authorization
server or sandbox. Anyone who can use the database can perform operator decisions.
Session IDs identify attempts; they are not authentication tokens. Do not expose the
Python API or database to untrusted clients or place the database on a shared host.

The ledger records explicit supplied context and evidence locally. It does not
redact secrets automatically. Store it outside public repositories; the default is
`~/.tessivolt/ledger.sqlite`. New storage directories use mode 0700 and the database
uses mode 0600. Existing directory permissions are not modified. Review permissions
when selecting a custom location. Use SQLite's backup API for consistent live backups.

No model or shell execution, telemetry, network listener, provider authentication,
or credential discovery is implemented. Scope and budget constraints govern the
ledger only; external agents must cooperate. A blocked session does not terminate
an external process, and expiry must be reconciled before a retry.

Report sensitive vulnerabilities through GitHub private vulnerability reporting if
enabled, rather than placing secrets or working exploits in public issues. If that
channel is unavailable, open a minimal issue requesting a private contact channel.
