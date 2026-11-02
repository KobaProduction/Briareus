# Control Plane backend architecture

## Responsibilities

Control Plane backend owns private human identity integration and adapts
UI management scenarios to owner contracts. It does not own
all account/runtime state, mount Node workspaces or expose a monolithic
administration database. Control Plane UI owns native human workflows.

Control Plane backend integrates private Rauthy for identity,
tokens/groups/roles and human Project access. Platform owns Team/Project
domain relationships and Node attachment. Resources owns shared source
catalog/bindings. Node owns local session/Cedar authority, files/resources,
module/container lifecycle and execution journal.

One Project UUID is shared across placements; Node UUID + Project UUID
selects independent local state. MVP Project members can manage all actions
within that Project, not unrelated Projects/host resources.

## API and event adaptation

Keep typed versioned browser-facing DTOs and adapt them to application
commands/queries. Source schema, generated types and actual published
routes must be reconciled before rollout; no invented endpoint is treated
as already live. Routers validate/serialize, never own business orchestration.

Authentication follows UI → backend → private Rauthy. Backend retains
provider session/challenge state and implements the pinned provider
protocol; Rauthy verifies passwords and issues identity tokens. No separate
infrastructure Authorization service exists. First-party service contracts
use native gRPC or WSS RPC adapters; UI uses WSS. Standard MCP/provider
protocols remain their supported interfaces.
All human sign-in/MFA/recovery screens remain in Control Plane.

Node management supports native gRPC and WSS/binary Protobuf with one schema
and shared use cases. Persistent bidirectional channels carry commands,
correlated results and ordered events, in either connection orientation.
Node signals pending requests; infrastructure notifies users and returns
authorized decisions. Reconnect does not repeat effects or approvals.

## Session and resource scenarios

Node Access owns session metadata, requests/grants/revocation and Cedar.
API adapts current human Project review to that owner. Automated approver
sessions operate locally without a synchronous UI/API dependency and cannot
appoint approvers or cross Nodes/control-plane scope.

Node can operate without the Panel. Its auto-approved mode confirms valid
sessions and all in-Project actions without manual grants or pending review.
Project isolation and session lifecycle always apply; infrastructure human
rights remain separate. See [mode contract](../architecture/session-access-modes.md).

In enforced mode grants target session UUIDs. Metadata is unverified review context and new
sessions inherit nothing. Each grant has its own deadline; activity refreshes
only idle state. Expiry preserves session/other grants and lets admitted work
finish. Explicit cancel/stop is separate; automatic idle cleanup is post-MVP.

Local and Team-shared resources use common narrow interfaces. Shared secret
values are delivered into Node durable storage; runtime resolves locally.
Control Plane initiates updates and periodic/reconnect reconciliation.
Node does not poll/fetch secrets per action. UI/log metadata omits values.

Files, Terminal, Browser and other modules share only their Project workspace.
Use Node contracts, not API filesystem mounts. Cross-Project/Node transfer
has explicit endpoints, independent checks and confirmed destination before
authorized source deletion. Files carry no session authority.

## Storage and observability

Use inward typed ports and owner-local persistence. Node supports SQLite/
PostgreSQL and optional local KV; central services retain their domain stores.
No cross-owner ORM sessions, global migrator or duplicate grant database.

Publish bounded operational events/metrics through explicit observability
ports. Avoid duplicating raw observability data into every owner database.
Do not export tokens, passwords, terminal stdin/output, browser forms or
arbitrary page content as telemetry. User-visible status comes from actual
owner results, not optimistic local mutation of revisions.

## Source and delivery

Keep domain/application/infrastructure/presentation inside each owner and
UI FSD boundaries intact. Shared packages contain focused reusable contracts/
capabilities with explicit consumers, not generic all-service state.

Complete all source owners before separately user-authorized tests/fixtures.
Then verify affected local runtime, lint/types, tests and mandatory hooks
against coherent proposed/outgoing batches. Agents may publish within the
task/approved Dev scope without approval per push. Avoid tiny pushes,
repeated unchanged CI, peer changes and unqualified data resets.

See [requirements](../architecture/engineering-requirements.md),
[topology](../architecture/infrastructure-hands-shared.md),
[Control Plane API](../control-plane-api.md) and
[quality policy](../../scripts/quality/README.md).
