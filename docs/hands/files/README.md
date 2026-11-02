# Files MCP module

Project filesystem operations, attachment ingress, bounded content reads/writes, directories and permitted in-Project copy/move/delete.

## Packaging and availability

The module has one source catalog directory under Hands, optionally grouped,
with its own Dockerfile, Compose, dependencies/lock and health/start contract.
Node instances deploy selected subsets without source copies. Catalog,
configured, installed, running and callable states are distinct.

Clients connect to this module's separate MCP endpoint through Node Gateway,
directly or through Control Plane ingress. Do not merge all module tools or
expose full container management through the MCP endpoint. Preserve the
module's registered schema and configured OAuth resource/audience.

## Project and session boundary

One logical Project UUID is shared with Control Plane; Node UUID selects
its independent local placement. A session uses its current Project and
selected session-access mode. Enforced mode requires exact operation/
resource grants; auto-approved mode confirms all valid sessions and their
in-Project actions without manual review. Project isolation, active session
binding and command/resource validation always apply. See
[mode contract](../../architecture/session-access-modes.md).
A path, catalog entry, metadata, public
header or connection alone creates no authority.

Node Gateway performs coarse admission and the module resolves the actual
canonical resource for an exact Node Access/Cedar effect decision. Shared
contracts/runtime plumbing have explicit consumers; do not duplicate policy
or import another owner's ORM/database.

Connected identity requirements apply as configured. Explicit standalone
mode can omit OAuth while retaining sessions/Cedar; an unavailable identity
service never silently selects anonymous mode.

## Owner behavior

An explicitly Node-wide common namespace is readable/writable by every
local Project without per-entry/grant restrictions, with observation/audit.
It is separate from private Project roots, homes, profiles, credentials and
native analysis stores; none are auto-published there. Path/link validation
cannot be bypassed through common storage. See
[storage contract](../../architecture/node-storage-and-transfer.md#node-wide-common-directory).

Files, Terminal and Browser downloads share only the selected Project workspace. Cross-Project/Node file or directory movement uses the external management transfer interface with both endpoint checks; ordinary paths cannot bypass it.

In enforced mode each grant has an independent deadline. Check it before admitting new work;
already admitted/started work may finish after expiry. Other grants and the
session remain. Explicit cancel/stop is separate; automatic idle cleanup is
post-MVP. Cleanup cannot delete shared Project files or unrelated active work.

## Delivery and evidence

Watch/build only this module and actual shared consumers. Source changes
do not prove deployed readiness or authorize an existing app/volume reset.
Preserve current data, credentials and qualified rollback. Complete source
owners before separately authorized tests; publish coherent locally validated
batches with mandatory hooks/protections.

See [owner contract](../../file-service.md),
[Node session access](../node/session-access.md) and
[shared runtime](../../shared/hand-runtime-capabilities.md).
