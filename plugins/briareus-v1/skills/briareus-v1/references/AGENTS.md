# Briareus V1 — agent entrypoint

**Scope:** this file applies to source on branch `v1`. The separate `v2` branch has its own architecture and agent policy. For Git and Server workspace operations, read [the active V1 Git/worktree policy](docs/operations/git-and-worktrees.md) before acting. That document owns the canonical checkout name, repository reuse, worktrees and cleanup; do not rely on a parent workspace file.

## Read by ownership, not by filename search

1. For any change: [project introduction](README.md), [documentation index](docs/README.md), and [core runtime architecture](docs/core/runtime.md).
2. For public ingress, UI, API or shared dependencies: [core services](docs/services/README.md), then the corresponding service's `README.md`.
3. For MCP behavior, browser, Git, files/jobs, analysis, telemetry or semantic tools: [Hands](docs/hands/README.md), then the specific Hand's `README.md`.
4. For Compose/Coolify, identity configuration, Git and data changes: [operations](docs/operations/README.md) and [deployment owner](https://github.com/KobaProduction/Briareus/blob/v1/deploy/README.md).
5. For migrations/tests: [test contracts](https://github.com/KobaProduction/Briareus/blob/v1/tests/README.md), [API test backends](https://github.com/KobaProduction/Briareus/blob/v1/services/control-panel/api/tests/README.md) and [local quality gate](docs/operations/testing.md).

Read any adjacent owner domain required by the change; never substitute a historical migration note for an active owner contract.

## Version and runtime boundaries

- V1 has **four core services** and **eleven optional MCP Hands** (current source catalog: `deploy/services.json`). Catalog inclusion does not mean deployed or healthy.
- **Control Panel API** owns account administration; no independent Management service. **Server Hand** owns files, terminal and jobs; no separate Files/Terminal/Curl MCP services. `curl` is only an optional terminal utility. The external identity provider owns human sign-in/tokens.
- V2 Node/Infrastructure/Cedar/grant architecture must not be silently mixed into V1. Live deployment details need independent Coolify/consumer verification.

## Work, validation and publication

Use one canonical checkout per repository and linked worktrees for concurrent work. Never modify or delete another agent's unpublished work without explicit owner coordination and recovery assessment. Keep workspace paths stable; do not generate task-named clones.

Change only the owning source/docs and necessary consumers. Preserve explicit runtime configuration, data/volumes, permission boundaries and provider behavior. After coherent edits, use affected tests and mandatory Git hooks; the final aggregate check is documented in [testing](docs/operations/testing.md). Do not weaken gates or conflate static checks with live acceptance.

Do not restart intentionally stopped Serena, deploy a retired Legacy resource, expose secrets or perform unrelated infrastructure changes. Existing historical documents are indexed under [history](https://github.com/KobaProduction/Briareus/blob/v1/docs/history/README.md) and are not operational authority.
