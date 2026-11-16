# V2 canonical source topology and repository policy

**Status: binding V2 owner policy.**

Binding source organization and repository constraints. Target layout is a specification, not proof that a current checkout or Coolify deployment has completed the migration.

See [topology](../architecture/infrastructure-hands-shared.md), [repository map](../repository-map.md), and the workspace-wide /workspace/projects/AGENTS.md.

**CANONICAL GIT REPOSITORY:** `KobaProduction/briareus`. Current Dev app Git source and agent App installation permissions require independent verification; see `docs/operations/BRIAREUS_DEV_ACCESS_SCOPE.md`.

**SOURCE TOPOLOGY:** docs/architecture/infrastructure-hands-shared.md. Infrastructure groups Control Plane UI/backend, panel Gateway, private backend Rauthy integration, Platform, Resources and external dependencies. There is no infrastructure Authorization service. Hands groups autonomous Node/Gateway/Access and Compose-based MCP modules; focused shared packages have explicit direct/transitive consumers. Flat services/ and root runtime modules are not the target.
