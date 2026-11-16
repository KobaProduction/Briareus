# Briareus V2 documentation

Choose the **owner first**. Long technical specifications remain linked rather than copied into one monolithic document.

| Domain | Primary entrypoint | Detailed owner contracts |
| --- | --- | --- |
| Core architecture and requirements | [Core](core/README.md) | [Engineering requirements](architecture/engineering-requirements.md), [topology](architecture/infrastructure-hands-shared.md) |
| Infrastructure / Control Plane | [Infrastructure](infrastructure/README.md) | [Human identity](infrastructure/identity-and-human-authority.md), [Control Plane RPC](control-plane-api.md) |
| Hands / Node / MCP | [Hands](hands/README.md) | [Node Access](hands/node/session-access.md), [storage](architecture/node-storage-and-transfer.md), [module source map](hands/modules.md) |
| Shared code and transport | [Shared](shared/README.md) | [RPC/resource delivery](shared/rpc-and-delivery-policy.md), [runtime module boundaries](shared/runtime-module-boundaries.md) |
| Implementation, Git, quality and rollout | [Operations](operations/README.md) | [Workflow](operations/implementation-workflow.md), [quality](../scripts/quality/README.md), [Dev scope](operations/BRIAREUS_DEV_ACCESS_SCOPE.md) |
| Decisions and provenance | [ADRs](decisions/README.md) | [Historical references](history/README.md) |

## Specialized contracts

- [Logical Project model](architecture/target-project-platform.md) and [session-access modes](architecture/session-access-modes.md)
- [Node resources and secrets](architecture/resources-and-secret-sources.md), [per-Project Files](file-service.md), [Terminal workspaces](architecture/terminal-workspaces.md)
- [Node Gateway/native gRPC/WSS](services/gateway/node-management-and-mcp.md), [MCP identity](oauth-chatgpt.md)
- [Clean Architecture/DDD adoption](architecture/clean-architecture-ddd-briareus.md), [repository map](repository-map.md)
- [Deployment](deployment.md), [acceptance/roadmap](roadmap.md), [agent coordination](operations/AGENT_COORDINATION.md)

## Evidence and precedence

**Binding rules** begin in [root AGENTS](../AGENTS.md) and its routed per-owner policy pages. This branch describes the **V2 target**. Source, static checks, local runtime tests, saved Coolify configuration and real deployed consumer acceptance are separate evidence. A diagram, target path or healthy process does not prove completed V2 capabilities.

The legacy MCP Bridge and V1 architecture are not deployment fallbacks for V2. Use the V1 branch's own README/AGENTS for V1 work. Never infer authorization to reset existing state or inspect resources outside the approved Development allowlist.
