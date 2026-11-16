# Infrastructure — Control Plane and external dependencies

Infrastructure owns human identity, Teams/groups, logical Projects and Node attachments, human management scope, the Control Plane UI/backend and coordination of Node requests. It **does not** own Node-local AgentSessions, Cedar decisions, execution journals or Node workspaces.

| Area | Owner documentation |
| --- | --- |
| Control Plane UI/backend and private Rauthy protocol | [Control Plane](control-plane.md), [native authentication](../services/api/native-login.md), [RPC and projections](../control-plane-api.md) |
| Human and administrator authority | [Binding identity policy](identity-and-human-authority.md), [identity requirements](../architecture/identity-and-session-access.md) |
| Project/Team/Node registry and shared resources | [Platform and Resources](platform-and-resources.md), [product/Project model](../architecture/target-project-platform.md) |
| External Rauthy, PostgreSQL, Valkey | [External services](external-services.md), [existing provider owner](../services/external/README.md) |
| Existing service-oriented implementation notes | [Service document index](../services/README.md) |

**No infrastructure Authorization service** is part of the V2 target. The retained services/authorization source and its allowlisted Dev app are migration inventory, not permission to reintroduce a central grant authority or delete its data.

These documents are **target ownership contracts**, not evidence that infrastructure/ has been fully populated, saved Coolify resources point to it, or the required private login flow has passed acceptance. See [deployment scope](../operations/README.md).
