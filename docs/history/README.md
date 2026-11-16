# V2 history and superseded designs

The target V2 architecture is **Infrastructure + autonomous Hands/Node + focused Shared packages**, not V1's deployed Control Panel/Gateway/Dependencies plus bundled Server Hand. Neither the retired Legacy MCP Bridge nor flat V1 source packages become V2 runtime authority.

Historical design material remains available where it explains decisions, but it is **not a deployment recipe**:

- [Early upstream-MCP/Bridge refactoring roadmap](../refactoring/mcp-upstream-roadmap.md): an older architecture audit.
- [Retired infrastructure Authorization migration](../services/authorization/service-folder.md): the existing resource and data are migration inventory; Node Access owns target session decisions.

**Not historical:** [Project Files transfer/migration](../files-migration.md) is an active V2 contract. It requires scoped Node/Project destination checks, integrity confirmation and separate authorization before source deletion.

Current implementation and rollout guidance belongs in [Infrastructure](../infrastructure/README.md), [Hands](../hands/README.md), [Shared](../shared/README.md) and [Operations](../operations/README.md). Do not delete protected legacy app resources, files, databases or credentials merely because their target architecture is retired.

Not everything under docs/refactoring/ is obsolete: the backend-control-plane and Development handoff texts still describe ongoing target migration considerations. A page's scope/status determines whether it is operative.
