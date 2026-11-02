# Module source and deployment cutover

Group target runtime under infrastructure/ and hands/, with focused shared
packages. Each deployable module owns source, Dockerfile, Compose, lock,
health/start and owner migrations. Nodes use a common MCP module catalog
without source copies per instance.

Inspect the actual checkout, dependency consumers and current approved Dev
Base/Compose/Watch before a move. Preserve public contracts, app UUIDs,
provider keys and durable state. Target paths are not evidence of saved
deployment configuration or completed data migration.

Watch/build only the module and actual shared consumers; docs do not trigger
runtime builds. An unrelated module must not restart because a different
shared package changed. No universal Compose restart or cross-owner migrator.

Complete all source owners before separately user-authorized tests.
Validate a coherent owned batch locally, including affected runtime,
lint/types, tests and mandatory hooks, before ordinary publication/scoped
Dev rollout. Avoid per-extraction pushes, repeated CI and unverified peer
changes; use isolated validation instead of resetting others' work.

Qualify real consumer behavior and independent recovery/rollback before
retiring an unused source/runtime path. Never infer an empty database,
delete a workspace/volume or rotate secrets merely to satisfy new source.

See [topology](../architecture/infrastructure-hands-shared.md),
[workflow](implementation-workflow.md) and
[approved scope](BRIAREUS_DEV_ACCESS_SCOPE.md).
