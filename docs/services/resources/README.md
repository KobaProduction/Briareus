# Resources and shared delivery

Infrastructure Resources owns Team-shared connections, variables, secret
source values and explicit Project/Node bindings. Node owns its local
resources and durable materialized secret values. Control Plane UI/API
adapts management scenarios through those owner contracts.

## Runtime autonomy

Shared values are delivered and stored in Node's database before use.
MCP operations resolve credentials locally, not by querying the central
catalog. A source reference/version records origin without making every
operation depend on infrastructure availability. Local resources work in
standalone mode with no external catalog.

Control-channel loss neither deletes the local value nor creates a cache
expiry. Actual provider credential expiry/revocation still applies.
An unavailable/invalid credential is not permission, an empty default or a
reason to switch sources silently.

## Synchronization

Control Plane initiates updates when sources/bindings change and periodically
reconciles desired versions against Node-reported applied versions.
Delivery uses the shared gRPC/WSS binary management contract.

Node validates target scope/version, persists updates atomically and
acknowledges operation/version/status without secret values. Preserve
idempotency and reject stale updates. On reconnect, Control Plane sends
pending differences; Node does not run a secret-catalog polling loop.

A remote change applies on Node after delivery. Disconnected Node retains
its last applied state; do not promise immediate remote invalidation.
A Node-initiated physical channel does not make Node the synchronization
initiator. Secret-source changes and session-access grants are separate.

## Scope and data

Bindings identify source/resource and Team/Project/Node scope. Metadata and
logs expose no token values. Protect durable values and resolve only the
material needed for the intended Project/resource operation. Infrastructure
checks human membership; Node Access independently applies the selected
session-access mode, requiring grants only in enforced mode and approving
valid in-Project actions automatically in auto-approved mode.

Preserve existing databases, accounts, credentials, provider volumes and
workspace files. This contract authorizes no reset or automatic live
migration. See [resource contract](../../architecture/resources-and-secret-sources.md)
and [quality phases](../../../scripts/quality/README.md).
