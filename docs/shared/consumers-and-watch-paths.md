# Shared consumers and build invalidation

Infrastructure services and MCP Hands own separate source, dependency locks, Compose and release lifecycles. A package is moved into shared/ only for **actual reuse**, and its narrowly scoped contracts must have explicit direct consumers. Build context/COPY and saved Coolify Watch Paths follow those direct and transitive dependencies.

Do not watch shared/** indiscriminately, copy an entire repository into every module image, or duplicate Node session/access, Gateway or transport code inside each Hand to avoid legitimate rebuilds. Conversely, implementation-specific Files/Terminal/Analysis use cases remain with their module owner; they are not generic shared client orchestration.

The repository already contains focused shared packages, but presence of a target layout document does not mean all source paths and deployed settings are migrated. Compare actual imports, generated images/Compose and each approved Development application's persisted Base/Compose/Watch before claiming build isolation.

Relevant contracts: [shared runtime module map](runtime-module-boundaries.md), [Hand capabilities](hand-runtime-capabilities.md), [target topology](../architecture/infrastructure-hands-shared.md), [deployment change matrix](../deployment.md#change-selection-and-restart-boundaries).

Changing a shared package should rebuild **only its actual deployable consumers**; only runtime/deployment observation can establish that this happened.
