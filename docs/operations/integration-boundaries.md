# Integration boundaries

Control Plane UI/API owns user-facing adaptation, not Node databases or a
global filesystem. Control Plane backend owns the private Rauthy integration;
native sign-in/MFA/recovery stays in the UI. No separate infrastructure
Authorization service exists. UI calls backend RPC over WSS; internal
first-party services use native gRPC or WSS adapters of typed Protobuf
service contracts. MCP and external provider protocols remain standard.

Infrastructure checks human Project access. Node management receives
authorized commands over native gRPC or WSS/binary Protobuf with shared
use cases and bidirectional events/results. Full trusted private control
and restricted MCP session calls are distinct surfaces.

Node Access owns local Project/session grants and Cedar; Gateway and modules
use the same owner contract at coarse and exact-resource boundaries.
Per-module MCP endpoints remain separate. Nodes need no central runtime
journal or user/group/team database. Each Node can start/operate without
the Panel. Its enforced/auto-approved switch controls operational approval
only: valid sessions and in-Project actions are automatically confirmed in
auto-approved mode, with mandatory Project isolation and session lifecycle.
See [mode contract](../architecture/session-access-modes.md).

Node UUID + logical Project UUID selects independent state and an isolated
workspace shared by its Project modules. Transfers check both endpoints,
including same-Node cross-Project operations. Shared resource values are
persisted locally; Control Plane initiates updates/reconciliation.

Watch/build inputs cover actual owner/shared consumers; unrelated modules
do not restart. Preserve existing data, credentials, app scope and qualified
rollback. Requirements, source and actual deployed acceptance are separate.

See [engineering requirements](../architecture/engineering-requirements.md)
and [workflow](implementation-workflow.md).
