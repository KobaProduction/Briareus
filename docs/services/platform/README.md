# Platform domain and Project registration

Infrastructure Platform owns human-facing Team/Project domain relationships
and central Node attachment. Human identity/groups/roles come from private
Rauthy through the Control Plane backend; Platform does not assign an independent
administrator role, store passwords or bootstrap another identity provider.

Use verified issuer/subject and stable domain references, not email matching,
browser JSON or arbitrary UUIDs as authority. MVP validates current Project/
group membership; a member may manage that Project fully. Per-action human
restrictions are deferred.

One logical Project has one UUID across Control Plane and Nodes. Registry
attachment records Node UUID + Project UUID, with no alternate local Project
ID. Local workspace/session/grant/resource/runtime state remains separate.
Node has no users/groups/Teams; management commands carry the infrastructure
decision without installing human IAM there.

Infrastructure owns user/Team/group relationships, human management scope,
logical Project definitions and Node attachment/placement accounting. It
initiates Project creation/management through Node RPC; the local Project,
its files and execution state are persisted by the target Node. A registered
Project can be present on one Node and absent on another. The registry
records that distinction without manufacturing a local placement.

Node-wide human management and Project-wide human access are infrastructure
scopes. Project-wide aggregation spans authorized placements of that Project;
Node selection does not expose unrelated Projects. Node receives only the
scoped management command and never copies human identities or memberships.

Platform does not own Node session grants/Cedar, filesystem or execution
journal. Node owns these through autonomous SQLite/PostgreSQL ports.
Infrastructure Resources owns Team-shared source catalog/bindings; values
are delivered into Node storage and updated by Control Plane reconciliation.

Owner transactions preserve object invariants, stable IDs, revisions,
idempotency and consistent audit/events. Do not import foreign ORM/database
sessions, run another owner's migrations, infer empty data or reset state
to match new source. Existing credentials, relationships and persistent data
remain protected until a qualified migration/recovery/rollback.

Source belongs in infrastructure grouping with own build/Compose/lock and
only actual shared consumers in Watch/build. Follow
[quality phases](../../../scripts/quality/README.md) and
[workflow](../../operations/implementation-workflow.md).
Runtime health/source interfaces do not prove accepted domain behavior.
