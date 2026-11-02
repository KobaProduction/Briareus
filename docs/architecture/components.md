# Briareus components

- Infrastructure Control Plane UI/API and panel Gateway provide human
  management/collaboration and ingress to attached Nodes.
- Infrastructure owns human identity, users/Teams/groups, Project access
  and Node-wide/Project-wide management scope. There is no separate
  infrastructure Authorization service or central session-grant authority.
- Platform/Resources own central domain objects, Node attachment and
  resource/integration metadata through their owner contracts.
- Node under Hands owns multiple isolated local Projects, its Gateway,
  module/container lifecycle, execution state and Node Access.
- Node Access owns AgentSessions, metadata, access requests/grants,
  audit/revocation and embedded Cedar decisions. No users/Teams/Rauthy.
- Node owns an explicitly common read/write directory for all local Projects,
  with observation/audit and no per-entry/grant restrictions. Private Project
  and analysis stores remain isolated. Node also installs panel-configured
  system tools, read-only to workloads, through consuming image/Compose lifecycle.
- Control Plane backend coordinates Node RPC and stores event projections
  for human views. Node owns authoritative requests/decisions; explicit
  active-request queries support manual refresh and reconnect reconciliation.
- Each MCP module has one source directory and its own Compose/dependencies.
  Node instances can deploy different subsets and expose available modules.
- Focused shared packages supply reusable contracts/transport/capabilities
  to explicit consumers. Watch/build inputs follow narrow dependencies.

Clients use separate module MCP endpoints through Node Gateway. Each retains
its catalog/protocol and configured OAuth audience. The Gateway does not
combine every module into an aggregate MCP endpoint; configured/ready module
sets can differ by Node.

Node management supports native gRPC and WSS/binary Protobuf in the first
iteration. Both use one message contract and shared command/result/event
scenarios, validators and access checks; only transport framing differs.

Direct and panel-proxied Node ingress use the same Node checks. Explicit
standalone mode can omit OAuth transport while retaining local Projects,
AgentSessions and Cedar. It is not an authentication-failure fallback.

Node can start and operate without the Panel. Infrastructure adds human
users/groups/Teams and management; agents use Node-local sessions rather
than becoming Node users. Node Access supports enforced and auto-approved
modes. Automatic approval confirms valid sessions and all in-Project actions
without manual grants; Project isolation always applies. See
[mode contract](session-access-modes.md).

See [Topology](infrastructure-hands-shared.md) and
[Identity/session access](identity-and-session-access.md).
