# Development rollout and recovery

## Source and publication boundary

Use grouped infrastructure/Hands source with focused shared consumers.
Finish all source owners before separately user-authorized testing.
Validate coherent owned batches locally: affected runtime, lint/types,
tests and mandatory hooks against the actual outgoing revision.

Agents may ordinarily publish within the task and approved Dev scope without
approval per push. main is Development where repository protections permit;
otherwise follow the required branch/PR path. Avoid tiny pushes, repeated
unchanged CI and unverified peer changes.

## Deployment qualification

The exact [approved scope](BRIAREUS_DEV_ACCESS_SCOPE.md), existing application
identities, data/volumes, routes and secret scopes remain binding. Source
registries/manifests and target paths are not proof of saved deployment
settings or runtime acceptance. Reconcile the candidate module, real
dependencies, Base/Compose/Watch and rollback before changing an app.

Each module has an independent lifecycle. Watch/build only its source and
actual shared consumers; an unrelated shared/external change must not
restart every app. Documentation does not trigger runtime builds.
Select aggregate image/check runs deliberately, not after every edit.

## State and bootstrap

Infrastructure owners migrate only their data. Rauthy initializes its own
empty provider and administrator; do not extract its password into service
secrets or rerun setup against populated state. Provider identity/storage
readiness does not run every service's migrations.

Node owns files, local Project/session grants and journal through selected
SQLite/PostgreSQL adapters and optional local KV stores. Control Plane outage
does not delete Node state. Shared resource values are delivered into Node
storage and reconciled by Control Plane. Never infer an empty database,
reset/migrate another owner or delete workspace/volume state to fit source.

Every logical Project retains its UUID; Node UUID selects independent local
placement. File migration/transfer is scoped and verified before authorized
source deletion. Preserve uncertain outcomes for reconciliation/rollback.

## Consumer acceptance and recovery

After authorized validation, verify actual human login/challenges/tokens,
Project membership, both Node management transports, connection orientations,
separate module MCP endpoints, Node-local session grants and workspace
isolation. Test actual allowed/denied effects and deadline behavior.
Health, source interfaces and image success are not these acceptances.

Observe only the changed approved app and real consumer paths. Maintain
previous qualified configuration/data and verify independent restart/recovery
before retiring unused runtime/source. Report unavailable dependencies and
partial migration distinctly from successful source/runtime acceptance.

No Production, unrelated resource inventory, plaintext secret read, new
app identity, speculative schema reset or mass Compose restart is implied.
