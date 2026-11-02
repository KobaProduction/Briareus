# Architecture overview

Infrastructure provides the Panel, Rauthy-backed human identity/roles,
central Projects, collaboration and Node attachment. Authentication goes
through Control Plane backend → private Rauthy. Backend owns the private
provider integration; no infrastructure Authorization service exists. All user-visible
sign-in/MFA/recovery stays in the Panel.

Hands provides autonomous Nodes. Each includes Gateway, local Projects,
Node Access/Cedar and module/container lifecycle. It has no user/group/team
database or Rauthy requirement. Nodes deploy different subsets of the common
Compose-based MCP module catalog.

Direct and panel-proxied ingress reach the same Node checks. Management
supports native gRPC and WSS/binary Protobuf through one contract and shared
use cases over bidirectional command/result/event channels. Full trusted
private control is distinct from restricted MCP session calls.

A Node can start and operate without the Panel or infrastructure services.
Its enforced/auto-approved session-access switch is independent of attachment
and OAuth. Auto-approved mode confirms all valid sessions and in-Project
actions without manual grants; Project isolation always applies. See
[mode contract](session-access-modes.md).

In enforced mode grants target session UUIDs, not inferred unique agents. Metadata is review
context; new sessions inherit nothing. Only human/operator management
appoints approver sessions, which cannot appoint others or cross Nodes.
Each grant has its own deadline. Activity refreshes only idle state;
admitted work may finish after expiry. Automatic idle cleanup is post-MVP.

Node owns files/state through SQLite/PostgreSQL ports and optional local KV.
Each Project workspace is shared by its modules and isolated from others.
External transfer covers files/directories across Nodes or Projects on the
same Node without transferring session authority.

Node's separate common directory is deliberately readable/writable by all
local Projects, with observation/audit and no per-entry/grant restrictions;
it exposes no private Project root or native analysis store. Panel-configured
system tools are installed by Node and used read-only by workloads. First-party
control uses typed gRPC service contracts through native gRPC or WSS RPC
adapters; browser UI uses WSS. Standard MCP/provider interfaces remain intact.

Focused shared packages rebuild only actual consumers. Source-first work,
separately authorized testing and validated batched publication follow the
[quality policy](../../scripts/quality/README.md).

See [topology](infrastructure-hands-shared.md),
[access](identity-and-session-access.md) and
[storage/transfer](node-storage-and-transfer.md).
