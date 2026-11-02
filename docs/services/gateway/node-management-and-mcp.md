# Node Gateway, management channel and session access

## Runtime and ingress

Node always includes Gateway, Node Access and management/runtime use cases.
Each Node can host multiple isolated local Projects and a different selected
set of Compose-based MCP modules. Known, deployed, running and callable
modules are distinct states. MCP module source is not copied per Node.

MCP clients reach a Node Gateway directly or through panel ingress routing
to that internal Gateway. Lack of a public IP does not remove the internal
Gateway. Transport adapters reuse the same Node admission/effect contracts.
The central panel is not the owner of local session-operation policy.

## Module MCP addresses

Expose separate MCP endpoints for Files, Browser, Terminal and other
configured modules through Node Gateway. Clients register/connect to each
module separately; the Gateway does not merge all tools into one MCP server.
The panel ingress preserves the target Node/module route when proxying.

Module discovery/readiness follows the actual Node deployment state, not a
fixed global tool list. Each module retains its own MCP contract/catalog
and configured OAuth resource/audience. Do not expose its unrestricted
container management merely because MCP traffic uses the same Gateway.

Node/Project AgentSession state is independent of a connection; one session
may use multiple endpoints for operations/resources on that Node within
its Project and selected Node session-access mode. Connection setup does not imply a tool-effect grant.
The gRPC/WSS management channel is distinct from the external MCP wire.

## Project placement identity

One logical Project uses one Project UUID across Control Plane and Nodes.
Routing/commands/events identify its placement by Node UUID + Project UUID,
not a translated local Project ID. Equal Project UUIDs on different Nodes
retain separate workspaces, sessions, grants and resource/runtime state.
Neither Gateway routing nor identity matching grants cross-Node authority.

## Full management interface

Expose Node management through both native gRPC and WSS with binary
Protobuf in the first iteration. Both adapters use one versioned Protobuf
command/result/event schema and the same application use cases. Native
gRPC uses HTTP/2; WSS uses binary frames. Neither is a REST/JSON CRUD API.

Both support persistent bidirectional channels, correlated typed results
and Node events. Share semantic validation, Node/Project/session scope,
Cedar authority checks, errors/results and audited idempotent execution.
Reconnect or switching transport preserves operation identity and does not
repeat an effect. Adapters own framing/connection lifecycle only. Protobuf
parsing alone does not satisfy semantic/authority validation. Configured
transport failure never enables unrestricted fallback behavior.

Allow either control-plane-initiated connectivity to a reachable Node or a
Node-initiated outbound connection. Both orientations preserve command
identity, Node/Project/session scope, ordered events and idempotent effects.
Do not infer a management grant from connection initiation or discovery.
Incremental discovery/registration does not require automatic attachment.

Trusted private MVP management connectivity needs no separate user/OAuth
or additional caller-authentication layer. The interface has full Node
control and remains separate from ordinary MCP session callers/untrusted
workloads. This does not enable public anonymous management. Node contains
no human users, groups, Teams or Rauthy.

Infrastructure checks human login and current Project/group membership.
In MVP a Project member can perform all management actions within that
Project. Per-action human restrictions are deferred; another Project on
the same Node remains isolated. Node accepts operator/control-plane commands
without implementing the human-role scenario itself.

## Session-access modes

Node supports enforced and auto-approved modes independently of Panel
attachment or configured OAuth. In auto-approved mode all valid sessions
and their in-Project actions are automatically approved without pending
review or individual manual grants. Gateway and modules use the same Node
Access decision, not separate switches. Session binding/lifecycle, Project
isolation and valid resources/commands remain mandatory. Only full trusted
management changes mode. Automatic approvals grant no approver/management
authority and no permanent grants when enforced mode resumes. See
[mode contract](../../architecture/session-access-modes.md).

## Session request and event flow (enforced mode)

Node durably creates and stores requests and their authoritative state.
It emits request/session/grant changes upward over the connected RPC
channel; it does not call an infrastructure authorization service for a
per-effect decision. Control Plane maintains a read projection for Node-wide
and Project-wide views and sends explicit management commands back.

Support authoritative management queries for all active requests, bounded
pagination and Node/Project/session/status filtering, exact-state lookup
and revision/cursor reconciliation. Both transports share these use cases.
Manual refresh and reconnect work even when events were missed; a stale
panel projection neither deletes pending requests nor grants operations.
The Node-initiated discovery connection and the backend-initiated direct
connection carry the same commands, results and upward events. Without
discovery, Node remains autonomous and the panel connects to its configured
Gateway; discovery initiates connectivity, never permission or attachment.

An MCP caller creates a Node-local AgentSession with untrusted review
metadata. Operational grants and approver authority target that UUID;
new sessions inherit nothing. Missing session returns session-required;
creation grants no protected operation.

A new access request becomes pending in Node Access. Node sends an event
over the management channel. Backend updates notifications/review for the
current Project's users. A human decision returns over the channel; Node
validates scope, records it and applies Cedar to subsequent operations.
Do not make Node contact users or represent pending notification as approval.

A human-appointed approver session can decide operational requests through
the restricted session API without waiting for a human. It operates only
inside its own Node and granted Project/resource scope; it cannot appoint
approvers, approve the same requesting session, manage another Node or
invoke unrestricted upstream/control-plane operations. No user/role/group
state is copied into the Node to implement this behavior.

## Operation admission

Node Gateway performs coarse connection/tool admission through Node Access.
MCP modules resolve the actual canonical resource and require the Node
Access decision for the selected mode: current Cedar grant in enforced mode,
automatic approval in auto-approved mode. Project isolation is unconditional. These are checks at distinct
boundaries against the same Node authority, not independent policy engines.
Gateway does not own human IAM, business resource parsing or provider keys.

In enforced mode each grant has its own scope and hard deadline. Activity refreshes session
idle state in Valkey without extending a grant; durable grants/revocation
are separate state. Expiration removes that access only, preserving the
session and other grants. An already admitted/started operation may finish;
new operations need a current grant. Explicit cancellation/session stop
are separate commands. Automatic idle shutdown/cleanup is post-MVP.

## Deployment and acceptance

Standalone Node needs no central panel/users/Rauthy and may explicitly omit
OAuth transport while keeping local Projects, AgentSessions and Cedar.
Connected authentication failure does not switch it to standalone mode.

Verify the selected module set, Project isolation, direct/proxied ingress,
management commands/results/events, reconnect/idempotency, pending request
notification and approval, Node-local approver restrictions and expiry.
Source contracts alone do not prove deployed transport or product acceptance.
Preserve existing deployment scope/data; this document authorizes no live
reset, public route, mass restart or new infrastructure.
