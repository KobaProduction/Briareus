# MVP runtime boundaries

Infrastructure owns Control Plane UI/API, private Rauthy-backed identity,
human/Team collaboration and central Project/Node registration. Native
authentication goes through Control Plane backend → private Rauthy, with
no separate infrastructure Authorization service. A verified
Project member may manage everything within that Project in MVP.

Node owns Gateway, Node Access/Cedar, isolated Project placements and
workspaces, sessions/grants, module/container lifecycle and durable state.
It has no human user/group/team database or Rauthy requirement. SQLite and
PostgreSQL adapters serve common inward persistence ports; optional KV and
delivered shared secrets are local to Node.

Clients connect separately to module MCP endpoints through Node Gateway,
directly or through Control Plane ingress. Module sets differ by Node.
Full management uses native gRPC and WSS/binary Protobuf over persistent
bidirectional command/result/event channels and common application use cases.

Node can start and operate without the Panel. Its explicit auto-approved
mode confirms valid sessions and all their in-Project actions without manual
grants. Enforced mode requires approvals; both modes preserve Project
isolation, session lifecycle and management boundaries. See
[mode contract](session-access-modes.md).

In enforced mode session grants and human/operator-issued approver authority target UUIDs.
Metadata is not unique agent identity; new sessions inherit nothing.
Approver sessions cannot appoint others or cross Nodes/control-plane scope.
Per-grant deadlines differ from inactivity. Expiry blocks new work while
admitted work finishes; automatic idle cleanup is post-MVP.

One logical Project uses one UUID everywhere; Node UUID + Project UUID
selects independent state. Each Project workspace is shared by its modules
and isolated from other Projects. External transfer handles files/directories
between Nodes or Projects on the same Node, without moving permissions.

Node also owns a separate read/write common directory for all local Projects,
with observation/audit and no per-entry or individual-grant restrictions.
Private Project roots and native analysis stores stay isolated. System tools
are separately panel-configured, Node-installed and read-only to workloads.
Browser/backend/internal control uses typed gRPC service/Protobuf contracts
via native gRPC or WSS RPC adapters; browser uses WSS and MCP stays standard.

Complete all source owners before separately user-authorized tests.
Locally validate coherent batches before autonomous scoped publication,
with mandatory hooks/protections and data-preserving rollout/rollback.

See [engineering requirements](engineering-requirements.md) and
[topology](infrastructure-hands-shared.md).
