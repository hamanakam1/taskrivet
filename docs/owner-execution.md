# Source-owner execution requests

Taskrivet can prepare and submit one explicit request to a separately configured,
local source owner that implements `taskrivet-execution-v1`. The owner keeps its
existing claim, readiness, authorization, pause, execution, and acceptance gates.
Taskrivet does not approve a ticket or launch a local process through this path.

This is an execution transport and reconciliation foundation. It does not select
additional tickets, run an unattended queue, rank model quality, create leases, or
mark work accepted. The `execution-observe` command follows one existing request
for a bounded number of reads and cannot submit anything.

## Bind the original source

Import the ticket first using `ticket-import`. Execution commands take its local
task ID and use the source origin stored at import. Changing the general ticket
service setting cannot redirect an existing request. This protocol accepts only
canonical numeric `M-` keys; another source needs an explicit protocol adapter.

Configure an explicit source-to-owner binding in the private config. These ports
are synthetic examples; replace them with the two origins you intend to bind:

```sh
python3 -m taskrivet config set execution.bindings \
  '[{"source_origin":"http://127.0.0.1:8123","owner_origin":"http://127.0.0.1:8124"}]'
python3 -m taskrivet config set execution.timeout 10
```

Both origins must be loopback HTTP origins without credentials, paths, or query
strings. There is no default owner and no fallback to another source. Redirects
and proxy environment settings are ignored or refused. The source owner must echo
the original source origin and exact canonical ticket key.

## Prepare, submit, inspect

```sh
python3 -m taskrivet execution-preflight LOCAL_TASK_ID
python3 -m taskrivet execution-prepare LOCAL_TASK_ID

# Copy the generated request_id from the preparation result.
python3 -m taskrivet execution-inspect REQUEST_ID
python3 -m taskrivet execution-submit REQUEST_ID
python3 -m taskrivet execution-status REQUEST_ID
python3 -m taskrivet execution-observe REQUEST_ID --count 10 --interval 2
```

All commands support `--format table`; JSON is the stable interface. Preflight
reads the imported ticket again and the owner's exact-card preflight. Preparation
persists an immutable request, original source and owner, imported work-definition
revision, and exact owner card, control, and route revisions. Preparation sends
no POST and repeated preparation for the same identity returns the same request.
An optional `--request-id` supports stable external integration IDs; reusing an ID
for different inputs is an error.

Submission reads the source and owner preflight again. A changed import, origin,
revision, hold, or route stops submission. The owner must recheck these gates at
its own admission boundary. Only an explicit `execution-submit` can POST, and it
commits the durable `submitting` state before entering network transport. Concurrent
submitters share that transaction and can consume only one local send.

Owner holds remain visible as reason codes. A held intent that has never been
sent can be explicitly prepared again after the source is re-reviewed. An intent
whose exact revisions changed requires a new preparation. Neither observation
nor service recovery automatically submits held work.

## Unknown outcomes and restart

The private SQLite journal is stored beside the selected ledger with the suffix
`.execution.sqlite`, or at the absolute `execution.journal_path` setting. Its
directory must be owned by you with mode 0700, and its file must be a regular file
owned by you with mode 0600. Preserve it across upgrades and restarts. It contains
identities, revisions, fixed reason codes, and minimized owner receipts; it does
not contain ticket detail, prompts, credentials, or executor reports.

A lost response, HTTP conflict, invalid receipt, or crash after the durable send
boundary requires an exact receipt GET. If the response was lost after the owner
committed, readback recovers the same request and preallocated run identity. If no
receipt can be confirmed, the outcome stays unknown. Even a 404 does not prove
the owner never received the POST. Submitting the same request again only reads
its receipt and never repeats its POST. This conservative rule also applies if
the process crashed before it actually reached the network.

`execution-inspect` reads local state without contacting the source or owner.
`execution-status` makes one receipt read. `execution-observe` makes at most 100
reads, with an interval of 0.1–30 seconds, and stops early when the owner reports
held or returned. An unavailable observation cannot erase a previously confirmed
receipt. A returned run still requires the source's independent review and
acceptance; it is not a completed-ticket claim.

## Route and cost limits

Every request includes exactly:

```json
{"allow_paid":false,"allow_unknown_entitlement":false}
```

There is no paid-budget override in this client. The supported owner contract
declares a configured `strict-local` route with `cost_class: zero_incremental`,
`qualified: false`, and `qualification: validated_on_call`. This is an explicit
local inference policy, not proof of current capacity or model quality. The owner
must validate its pinned local model and endpoint on every inference and deny
fallback to a paid or unknown lane. Source eligibility, installed model evidence,
and result acceptance are separate checks.

The constrained owner lane may also deny shell commands and optional model
helpers. Tasks requiring those capabilities can remain held or land in review.
This contract is not an operating-system sandbox or a global billing guarantee,
and the client does not widen the owner's tool policy to finish a task.

## Protocol and verification

The owner routes are `GET /execution/preflight?item=...`,
`POST /execution/requests`, and `GET /execution/requests/REQUEST_ID`. The exact
request binds `source`, `item`, `request_id`, `expected_card_revision`,
`expected_control_revision`, `expected_route_revision`, and `route_policy`.
Its receipt must echo that exact request and the SHA-256 digest of UTF-8 JSON
serialized with sorted keys, compact separators, and ASCII escaping.

Receipts have explicit request states (`held`, `requested`, `submitting`,
`outcome_unknown`, `owner_returned`), a preallocated owner run ID, and a minimized
result when available. Client envelopes always keep `execution_authorized: false`
and `source_acceptance_required: true`; eligibility and receipts do not grant
authority to another caller.

Synthetic tests exercise loss after owner commit, loss before commit, process
restart, duplicate and conflicting inputs, concurrent submitters, wrong source
and revision identities, changed controls, absent receipts, owner outages, cost
policy refusals, bounded observation, and the CLI. They do not invoke providers
or prove a particular installed owner is configured or available.
