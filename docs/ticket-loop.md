# Supervised ticket loop

Taskrivet can take one ticket you choose from a local ticket service, open the
agent you choose in a persistent terminal with a bounded context file, and post
a report back to the ticket when you confirm it. You make each decision. Nothing
in this loop picks work, claims a ticket, or runs an agent unattended.

```text
tickets / ticket ──► work KEY --tool NAME ──► attach / links / watch ──► handback ──► handback --confirm
   (read only)       import, session,         follow the agent and       preview      post through your
                     run folder, terminal     its ledger records                      adapter, read back
```

Taskrivet never changes a ticket's stage, tags, owner, or holds, and never marks
a ticket done. The only ticket write is a report you confirm.

## Setup

Examples use the installed `taskrivet` command. From a checkout, run
`python3 -m taskrivet` instead.

Settings live in a private file, `~/.taskrivet/config.json` by default
(`TASKRIVET_CONFIG` overrides the path). It must be a regular file owned by you
with mode 0600; Taskrivet refuses any other file. `taskrivet config set` writes
it atomically with mode 0600. It is not a credential store: keep tokens and keys
out of it.

| Setting | Meaning |
| --- | --- |
| `ticket_service.origin` | Loopback HTTP origin of a service that implements the ticket read protocol below. |
| `ticket_service.ticket_url` | Optional browser link template containing `{key}`, on a loopback origin. |
| `ticket_service.timeout` | Read timeout in seconds, 1–600. Default 30. |
| `ticket_adapter.argv` | Absolute path and arguments of your report adapter. Without it, reports can be previewed but not posted. |
| `ticket_adapter.timeout` | Adapter timeout in seconds, 1–600. Default 30. |
| `launchers.NAME` | A launcher override: `argv`, an optional `label`, or `disabled` with a reason. |
| `workdir` | Default working folder for `work`. Otherwise the current folder is used. |
| `runs_dir` | Where run folders go. Default `~/.taskrivet/runs`. |

```sh
taskrivet config set ticket_service.origin http://127.0.0.1:8080
taskrivet config set ticket_service.ticket_url 'http://127.0.0.1:8080/#/ticket/{key}'
taskrivet config set workdir "$HOME/src/project"
taskrivet doctor
```

The origin above is a synthetic example. `taskrivet doctor` checks Python, the
config file, the ticket service, the ledger, the session service, launchers, the
adapter, and the run folder. It starts nothing and writes nothing, and it exits
with status 1 when a check fails. `--offline` skips the ticket service.

## Commands

| Command | Purpose |
| --- | --- |
| `tickets [--q TEXT] [--status STATE] [--kind work\|case\|decision\|all] [--limit N] [--offset N]` | One page of tickets with readiness and holds. Defaults: all states, work items, 50 rows. |
| `ticket KEY` | One ticket: holds, objective, acceptance, linked tickets, and any local tasks bound to it. |
| `ticket-import KEY [--ack] [--refresh] [--scope KEY]` | Bind the current ticket revision to a local task. Launches nothing. |
| `work KEY --tool NAME [--ack] [--refresh] [--cwd DIR] [--lease SECONDS] [--no-prompt] [--dry-run]` | Import, start a ledger session, and open the agent in a terminal. |
| `sessions` | Terminals in this ledger's session service. |
| `attach ID [--no-follow] [--no-input]` | Replay a terminal's scrollback and follow it. `Ctrl-]` detaches. |
| `links [--ticket KEY] [--no-live]` | Ticket-linked tasks with their session, agent terminal, latest checkpoint, and report state. |
| `watch [--task ID] [--ticket KEY] [--after SEQ] [--interval SECONDS] [--count N]` | Follow ledger events as they are recorded. |
| `handback TARGET [--note TEXT] [--confirm]` | Preview a report for a task, or for a ticket's latest task. `--confirm` posts it. |
| `launchers` | Agent launchers you can pick, and whether each is ready. |
| `doctor [--offline]` | Setup checks. |
| `config show\|path\|get KEY\|set KEY VALUE\|unset KEY` | Read or change the private config. `VALUE` is JSON or plain text. |

A typical run:

```sh
taskrivet --format table tickets --limit 20
taskrivet --format table ticket DEMO-42
taskrivet work DEMO-42 --tool codex --dry-run
taskrivet work DEMO-42 --tool codex --ack
taskrivet attach 3f9c1a2b            # a unique prefix of at least 4 characters
taskrivet --format table links --ticket DEMO-42
taskrivet handback DEMO-42           # preview
taskrivet handback DEMO-42 --confirm
```

`sessions`, `attach`, `links`, `ticket`, and `doctor` never start the session
service. Ledger commands, `watch` included, reconcile expired leases as they read.

### Output and errors

JSON is the default and the stable interface for scripts. `--format table`, before
or after the subcommand, prints a view for people; `TASKRIVET_FORMAT=table` makes
it the default. `watch` prints one JSON object per line.

A failed command exits with status 2 and writes a JSON error to stderr, such as
`{"error": "...", "type": "HoldsPending", "ticket": "DEMO-42", "holds": [...]}`.
With `--format table` the error is plain text.

## Reading tickets

The ticket service must answer two GET requests with JSON:

- `GET /api/tix?status=STATE&limit=N&offset=N[&q=TEXT]` returns `generated_at`,
  `stale`, `total`, and `tickets`, plus `loading`, `errors`, or `refresh_error`
  when a read is incomplete.
- `GET /api/tix/ticket?key=KEY&seen=0` returns one ticket with its `detail`,
  `notes`, `tags`, `stage`, `readiness`, and `links_resolved`, or `{"error": ...}`.

Only loopback HTTP origins are accepted. Redirects and proxy settings are ignored,
and responses are size-bounded. A list the service reports as loading or
incomplete is refused instead of being shown as partial. A list is marked stale
when the service does not report it as fresh, when it has no usable timestamp, or
when it is more than five minutes old. A failed read is an error, never an empty list.

Ticket detail is bounded to 24,000 bytes and notes to 8,000 bytes, and anything
cut is marked. The objective and acceptance criteria come from lines labelled
`Objective:` or `Goal:`, and `Acceptance:`, `Acceptance criteria:`, or `Done when:`.
A ticket without acceptance criteria is imported with a note telling the agent to
ask you before treating the work as done.

The ticket revision is a SHA-256 hash of the key, kind, title, and detail. Stage,
tags, and readiness are not part of it: they are holds, read again on every `work`.

## Holds and acknowledgement

A hold is a known reason the ticket is not cleared for unattended execution:

- a `no-auto` tag, or a detail line saying the ticket is not authorized for
  autonomous execution
- an operator decision the source says is required
- the ticket is already active or executing, or its stage needs reconciliation or review
- readiness that is not `READY`, not verified, or stale
- blocking dependencies, whose state Taskrivet does not check

`work` refuses to launch while any current hold is unacknowledged. `--ack` records
that you reviewed the holds listed at that moment, as a `holds.acknowledged` event.
It clears nothing: the holds stay on the ticket and are written into the run's
context file. A later launch reuses your acknowledgement only while every current
hold was among the ones you acknowledged. A new hold needs `--ack` again.

## What `work` does

1. Reads the ticket and resolves the launcher you named.
2. Refuses if a hold is unacknowledged. `--dry-run` stops here and shows the plan.
3. Imports the ticket as a task named after it, such as `ticket-demo-42`, or reuses
   the open task already bound to it.
   The task reserves the resource key `ticket:<KEY>` plus any `--scope` keys. If
   the ticket's revision changed since the import, it refuses until you pass
   `--refresh`, which attaches the new ticket text and records `source.refreshed`.
4. Starts a ledger session owned by `taskrivet-work:<tool>`. The lease defaults to
   four hours and each checkpoint renews it. If the bound task is not ready, for
   example because it is still running or awaits review, `work` refuses: attach to
   its terminal, or decide the task first with `retry`, `accept`, or `cancel`.
5. Writes a run folder, `<runs_dir>/<task>/<first 12 characters of the session>/`,
   holding `context.md` (objective, acceptance, acknowledged holds, bounded ticket
   text, and the ledger commands), `ticket.json`, and `packet.json` (the task's
   context packet within 48,000 bytes). Folders are 0700 and files are 0600.
6. Opens the agent in a terminal of this ledger's session service, in the working
   folder, through `/usr/bin/env` with `TASKRIVET_TASK`, `TASKRIVET_SESSION`,
   `TASKRIVET_TICKET`, `TASKRIVET_CONTEXT`, and `TASKRIVET_RUN` set. When the
   launcher takes a prompt, the agent starts with a short prompt pointing at
   `context.md`. `--no-prompt` opens it without one.
7. Records `agent.launched` with the tool, terminal, and session.

If the terminal cannot be opened, the session is failed with category
`terminal_start`. If the service connection was lost mid-request, the failure
says the outcome is unknown: run `taskrivet sessions` before trying again.

The agent records progress with `taskrivet checkpoint`, `fail`, and `finish`, as
shown in its context file. `finish` moves the task to your review. Acceptance is
still your separate `taskrivet accept` decision.

## Launchers

A launcher says how to open an agent CLI with an initial prompt. Built-in profiles
cover tools whose prompt option was checked against their own `--help`:

| Prompt form | Tools |
| --- | --- |
| first argument | `claude`, `codex`, `droid`, `cursor-agent`, `cline`, `grok`, `vibe`, `qodercli` |
| `-i PROMPT` | `copilot`, `gemini` |
| `--prompt PROMPT` | `opencode`, `kilo` |

Any other installed agent found by `taskrivet tools` opens with no arguments. It
can still find its context through `TASKRIVET_CONTEXT`. Tools change their options
between versions, so a private launcher overrides a built-in profile:

```sh
taskrivet config set launchers.my-agent '{"argv": ["/opt/tools/my-agent", "--context", "{context}", "{prompt}"], "label": "My agent"}'
taskrivet config set launchers.claude.disabled 'Paid lane; needs approval first'
```

`{prompt}` and `{context}` are replaced inside arguments. The first element must
be an absolute path to an executable. With `--no-prompt`, arguments containing
`{prompt}` are dropped. A disabled launcher is refused with its reason.

## Terminals

The command line and the desktop share one session service per ledger. Its folder
is `~/.taskrivet/sessions-<12 hex characters>`, derived from the ledger path, and
`TASKRIVET_SESSION_DIR` overrides it. When the desktop has not started a service,
`work` starts a standard-library Python service with the same socket, token, and
protocol, so the desktop shows those terminals too. The service holds up to 24
terminals with up to 1 MiB of recent output each, in memory only. A Python
service whose socket is removed or replaced stops accepting connections and exits
once its terminals have ended.

`attach` replays the bounded scrollback and then follows live output. When stdin
is a terminal, your keystrokes and window size reach the agent; `--no-input` only
watches. `Ctrl-]` detaches and leaves the agent running. `--no-follow` prints the
scrollback and returns.

## Reporting back

`taskrivet handback TARGET` builds a report from the ledger and shows it: the local
task state, the latest session, the latest checkpoint's summary, evidence, and next
step, the finish evidence, self-reported tokens, recorded failures, and your
`--note`. Reports are bounded to 3,960 bytes — room is reserved so the appended marker
line still fits a 4,000-character note cap at the ticket service — and end by
saying that they do not accept the work or change the ticket. A preview never
calls the adapter.

`--confirm` posts the report:

1. The report is stored as pending with a stable marker, `taskrivet-handback:<id>`,
   appended after a blank line.
2. Taskrivet asks the adapter to `find` the marker. If the ticket already has it,
   the report is recorded as delivered and nothing is posted.
3. Otherwise it asks the adapter to `post`, then to `find` the marker again. Only a
   successful readback records the report as delivered.
4. Any error, timeout, or failed readback keeps the report pending, adds an attempt,
   and records the error. Running `--confirm` again reconciles through the same
   marker, so a post whose reply was lost is not duplicated.

Confirming the exact report that was already delivered posts nothing. `--confirm`
is refused when `TASKRIVET_SESSION` is set, because that shell belongs to an agent
run. This guards against accidents. It is not a security boundary.

### Adapter protocol

The adapter is any executable you configure in `ticket_adapter.argv`. Taskrivet
runs it once per operation, writes one JSON request to its stdin, and reads one
JSON object of at most 1 MB from its stdout. A non-zero exit, invalid JSON, or a
timeout counts as a failure whose outcome is unknown. The adapter inherits your
environment without the run-scoped `TASKRIVET_*` variables.

```json
{"protocol": 1, "op": "find", "ticket": "DEMO-42", "marker": "taskrivet-handback:0123456789abcdef"}
{"found": true}

{"protocol": 1, "op": "post", "ticket": "DEMO-42", "marker": "taskrivet-handback:0123456789abcdef",
 "body": "Taskrivet report for DEMO-42 ...\n\ntaskrivet-handback:0123456789abcdef",
 "sender": "Taskrivet", "role": "agent"}
{"posted": true}
```

Return `{"error": "reason"}` for any failure. An adapter must:

- keep `find` read-only, and report `found: true` only when a note on that ticket
  contains the marker
- add one note with the full body on `post`, and change nothing else: no stage,
  tags, holds, owner, or acceptance
- return an error, not `posted: true`, when it cannot tell whether the post landed
- use the ticket service's supported API rather than writing to its database
- keep its own credentials, for example by reading them from the OS keychain at
  call time. Taskrivet passes and stores none.

A minimal adapter that keeps reports in a local file shows the shape:

```python
#!/usr/bin/env python3
import json, sys
from pathlib import Path

store = Path.home() / ".taskrivet" / "example-notes.json"
request = json.load(sys.stdin)
notes = json.loads(store.read_text()) if store.exists() else {}
thread = notes.setdefault(request["ticket"], [])
if request["op"] == "find":
    print(json.dumps({"found": any(request["marker"] in note for note in thread)}))
elif request["op"] == "post":
    thread.append(request["body"])
    store.write_text(json.dumps(notes))
    print(json.dumps({"posted": True}))
else:
    print(json.dumps({"error": "unsupported operation"}))
```

## Boundaries

- You choose the ticket and the agent. Eligible, imported, or acknowledged does not
  mean authorized, and Taskrivet does not claim the ticket at its source.
- The agent runs as you, with your files, network, and credentials. It is not
  sandboxed, and ledger limits do not stop it.
- Ticket text is untrusted reference data. `work` writes it into the run folder,
  and the agent you launch may send it to its model provider.
- Tokens are self-reported, not measured billing. A finished session is not accepted
  work, and a delivered report is not acceptance.
- The ledger keeps ticket bindings and reports in schema 2. Existing ledgers gain
  the new tables in place, and earlier Taskrivet versions keep reading them.
