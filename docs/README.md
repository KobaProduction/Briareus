# Briareus documentation

## Requirements and architecture

- [Engineering requirements](architecture/engineering-requirements.md)
- [Product and Project model](architecture/target-project-platform.md)
- [Infrastructure, Hands and Shared](architecture/infrastructure-hands-shared.md)
- [Identity and session access](architecture/identity-and-session-access.md)
- [Enforced and automatic session approval](architecture/session-access-modes.md)
- [Node storage, common directory, system tools and transfer](architecture/node-storage-and-transfer.md)
- [Resources and secret sources](architecture/resources-and-secret-sources.md)
- [Control Plane backend RPC, UI and Node-wide/Project-wide views](control-plane-api.md)
- [Architecture overview](architecture/overview.md)
- [Component responsibilities](architecture/components.md)
- [Repository organization](repository-map.md)
- [Clean Architecture/DDD](architecture/clean-architecture-ddd-briareus.md)

## Runtime contracts

- [Node Gateway and binary management](services/gateway/node-management-and-mcp.md)
- [Project Files](file-service.md)
- [Terminal Project files and working directories](architecture/terminal-workspaces.md)
- [Browser authentication](services/api/native-login.md)
- [MCP identity and access](oauth-chatgpt.md)
- [Service documentation](services/README.md)

## Implementation and validation

- [Implementation workflow](operations/implementation-workflow.md)
- [Local quality and phases](../scripts/quality/README.md)
- [Deployment](deployment.md)
- [Approved Development scope](operations/BRIAREUS_DEV_ACCESS_SCOPE.md)
- [Roadmap and acceptance](roadmap.md)
- [Architecture decisions](decisions/README.md)

Requirements describe intended behavior. Source, local integration and
deployed acceptance are separate evidence; documentation, health or a built
image does not establish product completion. Preserve existing data and
qualify recovery/rollback rather than inferring a reset from source changes.
