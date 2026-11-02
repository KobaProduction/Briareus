# ADR 0001: Node-local resources and shared delivery

Status: accepted

## Decision

Node owns local Project connections/variables and durable secret values.
Infrastructure Resources owns Team-shared sources and Project/Node bindings.
Control Plane UI/API adapts human scenarios through owner interfaces.

Shared values are delivered into Node's database before use. MCP operations
resolve credentials locally without a per-action request to the catalog.
Local source values and delivered shared values serve the same use cases;
source references/versions retain explicit ownership and scope.

Control Plane initiates source-change delivery and periodic version
reconciliation over the existing gRPC/WSS binary channel. Node applies
updates atomically and acknowledges version/status without exposing values.
Reconnect/retry is idempotent and stale updates cannot overwrite newer ones.
Node does not poll the central secret catalog.

## Consequences

A disconnected Node retains its last applied local value, subject to actual
provider credential validity. Remote changes apply after delivery; no
instantaneous offline invalidation is promised. Source/secret versions and
session grants are independent authority. Metadata/logs expose no secret
values; existing data and credentials survive qualified migration.

Rauthy human identity/credentials are separate from external-service tokens.
Provider capability metadata is informational, not permission.

See [resource contract](../architecture/resources-and-secret-sources.md).
