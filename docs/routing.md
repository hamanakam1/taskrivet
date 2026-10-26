# Ticket routing observations

`ticket-route` reads a selected ticket and the optional engines inventory from
the configured local ticket service. It shows model routes and what evidence is
missing before a tool could be recommended for that ticket.

```sh
python3 -m taskrivet ticket-route DEMO-42 --url http://127.0.0.1:8080
python3 -m taskrivet --format table ticket-route DEMO-42
```

The origin above is synthetic. Set `ticket_service.origin` in the private
configuration or supply `--url`. The service must implement GET
`/api/tix/ticket?key=...&seen=0` and GET `/api/engines`. No ledger is opened and no
provider, model, probe, agent, or ticket mutation is invoked. Redirects and
proxies are disabled; reads have bounded response sizes and timeouts.

## What the result proves

The JSON schema is `taskrivet.route.v1`. It binds the observation to the returned
canonical ticket key and work-definition revision. A different returned ticket
key is accepted only when the source explicitly echoes the requested alias.
Ticket holds remain visible, including `no-auto` and unverified readiness.

Candidates come from `routing.routes`, with engine observations joined by the
route's `engine` identifier. Engine snapshots and completion probes are checked
separately for freshness; a new snapshot does not refresh an old probe. A
snapshot or probe older than five minutes, missing its timestamp, or more than
one minute in the future cannot count as current evidence.
The `source_current` field describes snapshot freshness only. An invalid or
stale snapshot has a null `expires_at`; a current snapshot still does not
qualify a model or refresh an older probe.

Imported task links include their original service `origin`. The native app
uses that explicit origin for routing reads, so changing the default service
cannot silently replace the source of an existing task. Missing origin data is
an unavailable binding, not permission to fall back to a different service.
Importing the same ticket key from another origin also refuses to reuse or
refresh an open task; reconcile the existing binding before changing sources.

The supported source protocol supplies inventory and engine-level observations,
not model-specific capability, context capacity, cost entitlement, comparable
accepted outcomes, or a qualified local launcher binding. Therefore candidates
are currently **held and unranked**, `selected` is null, and `cost_class` is
`unknown`. A route labelled local is reported as a source declaration. It does
not establish all the evidence needed for dispatch. Cloud aliases do not prove
the actual provider or authorize a paid fallback.

The `recommended` status is reserved for a future qualified routing contract;
this adapter never manufactures one from available engines or fast past turns.
An unsupported or unavailable endpoint returns `unavailable`, retaining any
ticket holds already read. `execution_authorized` is always false.

## Continuous work

This command is a read-only routing view, not a continuous executor. Automatic
work still requires source-owned claims, explicit execution grants, a verified
model-to-tool binding, budgets, durable attempt reconciliation, and source-owned
review. Existing supervised `work` and report confirmation remain separate.

Output can contain private ticket identifiers, model aliases, and service
origins. Keep it local. The projection omits provider credential references,
probe replies, process paths, and unrelated historical ticket activity.
