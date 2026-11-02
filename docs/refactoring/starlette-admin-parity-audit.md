# Control Plane feature contracts

Feature presentation adapts current owner scenarios; this matrix states
responsibilities and does not claim every runtime feature is implemented.

| Surface | Owner-backed behavior |
| --- | --- |
| Human identity | Native sign-in/MFA/recovery through backend RPC/WSS → private Rauthy; backend owns the provider protocol |
| Teams/Projects | Current membership, domain relationships and one Project UUID |
| Nodes | Attachment, placement, configuration and actual module availability |
| Session access mode | Actual Node enforced/auto-approved setting; automatic decisions without invented human approval; mandatory Project isolation |
| Session requests | Enforced-mode metadata/scope/deadlines, pending notifications and confirmed decisions |
| Approver sessions | Human/operator appointment, Node-local operational approval only |
| Files | Project workspace operations and explicit scoped transfer |
| Terminal | Project jobs, logs/PTY and separately authorized cancellation |
| Browser | Project profiles/tabs/automation and intended captures/downloads |
| Analysis | Provider-native Project state and controlled import/export |
| Provider connections | Local resources and delivered Team-shared bindings |
| Settings | Typed owner-backed configuration with explicit applicability/status |
| Observability | Bounded redacted events/metrics and real owner outcomes |

Project membership permits all actions in that Project in MVP; finer human
permissions are deferred. Session grants remain independent. Metadata does
not prove unique agents, and UI enablement/action hints are not authority.

Show Node UUID + Project UUID placement and separate session/per-grant states.
In enforced mode expiry blocks new actions under that grant while admitted work finishes,
preserving session/other grants. Explicit stop/cancel is separate.

Node operations go through owner contracts using shared gRPC/WSS management.
UI never directly calls private full control or mounts Node data. A timeout
is uncertain; reconcile exact operation identity/revision rather than invent
success, increment revisions or blindly retry a new command.

The same Project workspace is shared only within that Node placement.
Cross-Project/Node file movement checks both endpoints and transfers no
session permission. Metadata/logs show no secret values.

Follow FSD/typed boundaries and separately authorized aggregate validation.
Source, visual preview and health are not accepted user behavior.
See [UI contract](../services/ui/mcp-module-migration.md) and
[API responsibilities](../control-plane-api.md).
