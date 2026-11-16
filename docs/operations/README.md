# V2 operations, engineering and documentation

Operations describe **how changes are planned, validated and released**, separately from Infrastructure human authority, Hands Node execution and Shared contracts.

| Topic | Source of authority |
| --- | --- |
| Agent ownership, source/test phases and coordination | [Owner policy](source-ownership-policy.md), [implementation workflow](implementation-workflow.md), [agent coordination](AGENT_COORDINATION.md) |
| Publication and access limits | [Binding release/scope rules](release-and-scope-policy.md), [strict Coolify Development allowlist](BRIAREUS_DEV_ACCESS_SCOPE.md) |
| Static/quality requirements | [Local quality policy](../../scripts/quality/README.md), [Clean Architecture adoption](../architecture/clean-architecture-ddd-briareus.md) |
| Deployment and change selection | [Deployment requirements](../deployment.md), [Development rollout](development-rollout.md), [layout transition](service-layout-transition.md) |
| Git and parallel worktrees | [Repository/worktree workflow](git-and-worktrees.md), workspace-wide AGENTS policy |
| Documentation maintenance | [Documentation checks](documentation-maintenance.md), [owner index](../README.md) |

**Current V2 source organization is transitional.** The target groups Infrastructure, Hands and focused Shared, but the checkout still includes services/ and hands/ source. Never infer the saved Coolify Base/Compose/Watch configuration or a completed data cutover from a target documentation page.

### Source versus test authorization

The existing V2 source phase prohibits running/writing/adapting tests until its separately authorized aggregate test phase. Scoped static and document-link checks are permitted. Publication rules require coherent batch validation and mandatory hooks; do not silently weaken or bypass those requirements for a source change.

This documentation restructuring is **not** a source-phase completion claim, a test-phase authorization, a CI repair, or approval to browse/deploy outside the exact existing Development allowlist. See [known documentation/CI boundaries](documentation-maintenance.md).
