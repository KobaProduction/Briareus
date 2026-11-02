# Autonomous Node runtime

Node includes Gateway, local Projects, Node Access/Cedar, AgentSessions,
Compose-based MCP module management and execution state. It contains no
human user/group/team database or Rauthy subsystem. It can start, manage
local Projects/modules and execute work without the Panel or any external
infrastructure service.

One logical Project keeps the same Project UUID in Control Plane and all
Node placements. Workspace/session/grant/resource/runtime state is local
to Node UUID + Project UUID; no separate Project-ID translation, shared
mount, state replication or cross-Node session inheritance is implied.

## Local state

Node owns its persistent files/workspaces, Project/session/grant state,
module records and execution journal. Application persistence ports support
SQLite and PostgreSQL adapters with the same transaction, revision,
operation/replay and event-ordering invariants. Select the backend explicitly;
no failure-driven backend fallback or empty-state reset is allowed.
Optional Valkey/KV and computational stores belong to the Node contour.
A central Resources journal is not a required runtime storage dependency.

## Management and session access

Gateway exposes native gRPC and WSS/binary Protobuf management adapters with
one contract and shared use cases. Control-plane and Node-initiated channels
support commands, results and events. Full private management is distinct
from limited MCP session operations; only the latter depend on the specific
session's access under the selected mode. Standalone mode does not
fabricate human IAM. Node Access has enforced/auto-approved modes; the
latter automatically approves all valid sessions and their in-Project
actions without manual grants. Project isolation, active session binding
and validation are unconditional. Only full management changes mode;
automatic approval grants no approver/management authority or permanent
grants on return to enforced mode. See
[mode contract](../../docs/architecture/session-access-modes.md).

Operational grants and human/operator-issued approver authority target an
AgentSession UUID, Node and Project/resource scope. Approver sessions cannot
appoint other approvers, cross Nodes or gain control-plane privileges.

## Project workspaces

Each local Project owns one persistent workspace used by its Files,
Terminal, Browser and other modules. Sessions do not own duplicate Project
trees, and their paths/metadata cannot select a sibling Project. Isolate
workspace, terminal home, browser profile and private runtime state at the
filesystem/process boundary. Normal MCP commands cannot transfer across
Projects by using host paths or traversal.

## Module endpoints

Node provides a separate persistent common directory readable/writable by
all local Projects without per-entry or individual-grant restrictions,
with session attribution, observation/audit and no automatic exposure of
private Project or analysis data. It is distinct from system toolchains:
panel chooses tools/versions, Node installs them through consuming image/
Compose configuration, and workloads use system installations read-only.
Project-local environments remain writable. See
[storage/tools](../../docs/architecture/node-storage-and-transfer.md#node-wide-common-directory).

Files, Browser, Terminal and other modules have separate MCP endpoints
through Node Gateway, not one merged tool server. A Node/Project session may
use several module endpoints within its Project and session-access mode. Direct and panel-
proxied ingress preserve the selected Node/module and MCP contract.

## File interfaces

Provide upload/download and explicit file/directory transfer through the
Node contract with target Node UUID and target Project UUID. The same
interface covers another Project on this Node or a different Node. Each endpoint checks its own scope; data carries no session
permission. A move confirms destination write/integrity before separately
authorized source deletion. Preserve operation identity across retries.

See [Topology](../../docs/architecture/infrastructure-hands-shared.md)
and [Storage/transfer](../../docs/architecture/node-storage-and-transfer.md).
The specification does not establish complete runtime implementation or
qualify a live cutover. Preserve existing journal files, databases, volumes
and credentials; migration/recovery/rollback require separate acceptance.
