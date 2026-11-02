# Briareus

Canonical repository: [KobaProduction/briareus](https://github.com/KobaProduction/briareus).

Briareus combines infrastructure control with autonomous execution Nodes.
Runtime source is grouped under infrastructure/ and hands/; focused shared
packages have explicit consumers and narrow build watches.

Infrastructure supplies the Panel, users/Teams, central Projects and Node
attachment. Native sign-in/MFA/recovery uses UI → Control Plane backend →
private Rauthy. Backend owns the private provider integration; Rauthy owns
credentials/tokens/groups/roles. No infrastructure Authorization service exists.
In MVP a Project member can manage everything within that Project.

Each Node includes Gateway, Node Access/Cedar, isolated local Projects,
its selected Compose-based MCP module set and autonomous storage. Direct
and panel-proxied ingress reach the same checks. Standalone Node needs no
central panel, users/Teams/Rauthy or runtime storage; it can start and
manage Projects/modules without those external services.

A logical Project has one Project UUID everywhere. Node UUID + Project UUID
selects its independent workspace, sessions, resources and runtime state;
there is no local-ID translation or implicit cross-Node synchronization.

Clients connect separately to Files/Browser/Terminal and other module MCP
endpoints through Node Gateway. The Gateway routes modules rather than
merging all tools. Direct and panel-proxied access preserve that selection;
a Node/Project session may use several endpoints within its Project under
the selected session-access mode.

Node has an explicit enforced/auto-approved switch. Auto-approved mode
automatically confirms all valid sessions and their in-Project actions
without manual review. Project isolation always applies; automatic approval
gives no full management or approver authority. See
[session-access modes](docs/architecture/session-access-modes.md).

In enforced mode, grants and human/operator-issued approval authority target session UUIDs.
Metadata does not prove a unique agent/chat; new sessions inherit nothing.
Approver sessions cannot appoint approvers or cross Nodes. Each grant has
its own deadline: expiry blocks new work while admitted work finishes and
other grants/session state survive. Activity refreshes only an idle clock.

Node owns files/state through SQLite/PostgreSQL ports and optional local KV.
Each Project workspace is shared by its modules and isolated from others.
External transfer covers files/directories across Nodes or Projects on the
same Node without transferring session authority.

Node management supports native gRPC and WSS/binary Protobuf with one
contract and shared use cases over bidirectional command/result/event
channels. Full trusted private control is separate from MCP session calls.

First-party UI/backend/internal control uses typed gRPC service/Protobuf
contracts, with native gRPC and WSS RPC adapters. Browser UI uses WSS;
MCP and external providers retain their standard protocols. Panel views
group Node-owned requests Node-wide or Project-wide and reconcile event
projections through explicit active-request queries.

Project-private files remain isolated. An explicitly Node-wide common
directory is readable/writable by all Projects, with observation/audit;
it is not another Project's private storage. System toolchains are installed
by Node from panel-managed configuration and used read-only by workloads.

Team-shared secrets are delivered into Node durable storage for local use.
Control Plane pushes source updates and reconciles versions periodically/
after reconnect; Node never polls secrets per operation. See
[resource delivery](docs/architecture/resources-and-secret-sources.md).

Finish all source owners before separately user-authorized testing.
Publish coherent owned batches after local runtime/lint/type/test/hook
validation; avoid per-action pushes and repeated unchanged CI. Preserve
existing state, approved Dev scope and required protections. Requirements
do not establish runtime completion.

Start with [documentation](docs/README.md),
[topology](docs/architecture/infrastructure-hands-shared.md),
[identity/access](docs/architecture/identity-and-session-access.md)
and [quality policy](scripts/quality/README.md).
