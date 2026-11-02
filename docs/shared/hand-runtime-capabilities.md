# Shared MCP runtime contracts

Shared code contains small stable contracts, transport adapters and reusable
capabilities with explicit consumers. It does not own human IAM, Project
business data or duplicate session policy in every MCP module.

## Binding and effect checks

A module declares its tool/action vocabulary and typed canonical resource
binding. Its owner resolves actual arguments to the current Project/resource.
Node Gateway requests coarse admission; the module requests the exact effect
decision from Node Access/Cedar through a common inward-facing port.
A tool name/catalog entry is not a resource grant. Node Access owns both
enforced Cedar-grant decisions and the explicit auto-approved mode. The
latter automatically approves valid sessions and in-Project actions, while
Project isolation and session lifecycle always apply. Adapters do not copy
or override that mode; see [mode contract](../architecture/session-access-modes.md).

Node UUID + logical Project UUID selects local session/resource state.
Caller headers, friendly names and host paths cannot create trusted context.
Connected identity/audience verification is configurable by the explicit
deployment mode; standalone mode may omit OAuth without omitting sessions/
Cedar. No failed identity check silently selects another mode.

## Results, lifecycle and transport

Resource binding distinguishes private Project files, the explicit Node-wide
common read/write namespace and read-only system-tool installations. Common
storage is available to all local Projects without per-entry or individual
grant restrictions; preserve active session/Node attribution, observation/
audit and path/link isolation from private data. System tools are installed
by Node from panel-managed configuration. Shared adapters implement these
same Node contracts rather than inventing module-specific ACLs.

Use named typed input/results and outer serialization; no ordinary dictionary
application contracts, Any or shared owner ORM imports. Preserve module MCP
wire schemas and separate endpoints, not one merged tool namespace.

Share gRPC/WSS management schemas and use cases without per-transport policy.
Preserve operation identity, revisions, scoped idempotency and event ordering.
A reconnect/timeout is not proof that an effect did not commit.

In enforced mode check the applicable grant for new work. Admitted work may finish after
expiry; unrelated grants/session state survive. Explicit cancel/stop is
separate. Cleanup must not delete shared Project data or other sessions' work.

## Package and acceptance boundaries

Break broad helpers into capabilities/contracts with known consumers and
stable APIs. Watch/build only actual package dependencies. Do not force all
modules to import provider-specific behavior or a universal runtime package.

Shared packages declare their direct consumers and dependencies on other
focused shared packages. Build/watch selection follows that transitive
graph. Reuse common transport, Gateway plumbing and typed Node Access
interfaces once; keep session-policy authority in Node Access and changing
provider/tool implementations in their own modules. A module-only change
updates only that module's containers, without restarting Node or siblings.

Source integration, registered tools, configured deployment and callable
readiness are distinct. Follow source-first work and separately authorized
aggregate tests; source/health alone does not establish protected effects.
See [Node session contract](../hands/node/session-access.md).
