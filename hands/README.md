# Hands and autonomous Node runtime

Hands groups Node/Gateway/Access and the MCP module source catalog.
Each module has one directory, optionally grouped, with its own source,
Dockerfile, Compose, dependencies/lock and health/start contract. Node
instances select different module/container sets without source copies.

Node owns local Project/session authority and autonomous storage and can
start/operate without the Panel. Enforced mode uses Cedar grants; the
auto-approved switch confirms valid sessions and all in-Project actions
without manual grants. Project isolation is mandatory in both modes. See
[mode contract](../docs/architecture/session-access-modes.md).
Clients use separate module MCP endpoints through Node Gateway, directly
or through Control Plane ingress. Coarse admission and exact module effects
use the same Node Access contract, not central grant/database calls per action.

Project UUID is common across placements; Node UUID selects isolated local
workspace/session/resource state. Full private management and limited MCP
session operations are distinct. gRPC/WSS management adapters share contracts
and use cases. Watch/build only actual module/shared consumers.

See [topology](../docs/architecture/infrastructure-hands-shared.md),
[session access](../docs/hands/node/session-access.md) and
[module documentation](../docs/shared/runtime-module-boundaries.md).
