# Deployment artifacts and qualified cutover

Runtime packaging belongs to grouped infrastructure/Hands modules with
focused shared consumers. Existing deployment artifacts are not proof that
target source paths, saved settings or data layout already match.

Before replacing any deployed artifact, qualify the actual app identity,
Base/Compose/Watch, persistent state, consumer contracts and rollback.
Preserve existing databases/volumes/keys/workspaces. An unused source path
does not authorize resetting live state or creating another app.

Finish source owners before separately authorized tests. Publish coherent
locally validated owned batches with mandatory hooks/protections; no tiny
push/CI loop. Use only approved Development scope, never unrelated resources,
plaintext secrets or Production.

See [deployment requirements](../docs/deployment.md),
[cutover](../docs/operations/service-layout-transition.md) and
[access scope](../docs/operations/BRIAREUS_DEV_ACCESS_SCOPE.md).
