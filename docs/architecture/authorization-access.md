# Human identity and session access

Control Plane backend privately integrates Rauthy for human identity,
groups/roles and rights. Panel authentication uses UI → backend → private
Rauthy with native Panel login/MFA/recovery screens and browser RPC over WSS.
No separate infrastructure Authorization service exists. In MVP a Project
member can manage all actions within that Project.

Node Access is part of Node runtime. It owns local Project-scoped
AgentSessions, requests/grants/revocation and Cedar decisions. Node has no
human users/groups/Teams or Rauthy. Connected infrastructure sends authorized
management commands; Node applies them without a duplicate human IAM model.

Node can operate without the Panel. Its explicit auto-approved switch
automatically confirms valid sessions and all their in-Project actions;
Project isolation always applies. Human infrastructure rights and full
management authority are unchanged. See [mode contract](session-access-modes.md).

In enforced mode operational access and approval authority target session UUIDs. A caller
may create multiple independent sessions; metadata is unverified review
context and new sessions inherit nothing. Only human/operator management
appoints an approver session. It may grant operations only within its Node
and approved scope, never appoint approvers, self-approve the requesting
session or gain privileged control-plane management.

Per-grant deadlines and session inactivity are separate. Activity refreshes
Node-local idle tracking without changing grants. Expiry blocks new work
under that grant while admitted work finishes; the session, other grants
and new-request capability remain. Explicit cancellation/stop is separate
and requires the applicable privilege. Automatic idle cleanup is post-MVP.

Each Project workspace is shared by its modules and isolated from others.
Cross-Project/Node movement uses the external transfer interface and checks
both endpoints. Paths/metadata cannot switch Project or carry authority.

Node's separate common directory is deliberately readable/writable by all
local Projects without per-entry or individual grants, with observation/
audit and no automatic exposure of private Project data. It is not another
Project's private root. System tools are a different Node-managed resource:
panel selects their configuration, Node installs them through consuming
image/Compose definitions, and workloads use the installation read-only.

Direct and panel-proxied ingress reach the same Node Gateway/Access and
module effect checks. Full trusted private management uses native gRPC and
WSS/binary Protobuf with shared use cases, separate from MCP session calls.
Explicit standalone mode may omit OAuth while retaining local sessions and
Cedar; connected authentication failure never changes modes.

Detailed contracts: [identity/session model](identity-and-session-access.md),
[Node/Gateway](../services/gateway/node-management-and-mcp.md),
[storage/isolation](node-storage-and-transfer.md) and
[source/test phases](../../scripts/quality/README.md).
