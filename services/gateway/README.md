# Gateway transport and ingress

Gateway has infrastructure ingress and Node ingress roles through shared
focused transport contracts. Node always includes Gateway and Node Access/
Cedar. Clients connect separately to Files/Browser/Terminal/other configured
MCP module endpoints, directly or through Control Plane ingress.

Preserve the selected Node/module and exact Project/session context.
Catalog presence, headers, a connection or coarse Permit is not permission
for a tool/resource effect. Each module resolves its canonical resource and
uses the same Node Access authority. Gateway does not own human roles or
module business argument interpretation.

Node management supports native gRPC and WSS/binary Protobuf, one schema and
shared application use cases. Persistent bidirectional commands/results/
events preserve scope/idempotency across reconnect/transport changes.
Full trusted private control is not an ordinary MCP session surface.

Preserve bounded streaming, query/body/status and legitimate end-to-end
metadata; reject malformed/ambiguous framing rather than forwarding guessed
identity or aliases. Do not inspect UI assets to fabricate responses or
expose provider management via generic route passthrough.

Human sign-in/MFA/recovery stays in Control Plane UI; infrastructure
Control Plane backend privately integrates Rauthy. Configured connected identity/
audience rules apply; explicit standalone may omit OAuth while retaining
sessions/Cedar. Failed identity never enables anonymous fallback.

Node Access owns the enforced/auto-approved switch. Automatic mode confirms
valid sessions and all in-Project actions without manual grants; Project
isolation, session lifecycle and command/resource validation always apply.
Only full management changes mode, without granting approver authority. See
[mode contract](../../docs/architecture/session-access-modes.md).

In enforced mode check grants at new-operation admission; admitted work may finish after
expiry. Explicit stop/cancel is a separate command. A connection timeout or
lost reply is not proof an effect failed to commit.

Packaging/watch inputs are owner-scoped with actual shared consumers.
Preserve source/public protocol compatibility, existing state and qualified
rollout/rollback. Follow source-first and separately authorized testing;
health/source is not deployed acceptance.

See [management/MCP](../../docs/services/gateway/node-management-and-mcp.md),
[admission](../../docs/services/gateway/runtime-admission.md) and
[topology](../../docs/architecture/infrastructure-hands-shared.md).
