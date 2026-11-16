# Briareus V2 — Infrastructure, autonomous Nodes and MCP Hands

Briareus V2 is the **target architecture** for central Infrastructure (human identity, Control Plane, Teams and Projects), autonomous execution Nodes with Node Access/Cedar and independent MCP modules, plus focused Shared contracts.

**Important:** requirements and source declarations do not establish that the planned source migration, deployment cutover, native gRPC/WSS acceptance, user login or session/project isolation are completed. V1 is a separate maintained branch and product architecture.

## Documentation by owner

| Entry | Responsibility |
| --- | --- |
| [Agent instructions](AGENTS.md) | Mandatory engineering rules and owner-specific binding policies |
| [Core](docs/core/README.md) | Target system boundaries, engineering requirements, architecture |
| [Infrastructure](docs/infrastructure/README.md) | Control Plane UI/backend, private Rauthy, Platform, Resources, external dependencies |
| [Hands](docs/hands/README.md) | Autonomous Node, Gateway, Node Access/Cedar, local Projects, independently deployed MCP modules |
| [Shared](docs/shared/README.md) | Typed gRPC/WSS contracts, resource delivery, small shared packages and consumers |
| [Operations](docs/operations/README.md) | Agent coordination, phases, quality gates, restricted Development scope and Git/worktrees |
| [Architecture decisions](docs/decisions/README.md) | Accepted decisions and consequences |
| [History](docs/history/README.md) | Older or superseded design and migration records |

The full [documentation index](docs/README.md) routes to detailed requirements, including [identity/session access](docs/architecture/identity-and-session-access.md), [Node storage/transfer](docs/architecture/node-storage-and-transfer.md), [session-access modes](docs/architecture/session-access-modes.md), [resource delivery](docs/architecture/resources-and-secret-sources.md) and [Node RPC](docs/services/gateway/node-management-and-mcp.md).

## Core distinctions

- **Infrastructure** owns Rauthy-backed human identity, Teams/groups, logical Projects, placement and Control Plane management. UI signs in through the Control Plane backend's **private** Rauthy integration. No independent infrastructure Authorization service is the target.
- **Each Node** owns Gateway, Node Access, one private workspace per local Project, AgentSessions and grants/revocation, local resources/storage and selected MCP modules. It can run independently of the Panel.
- **Session modes:** enforced mode uses Node-local Cedar grants; auto-approved mode admits valid sessions and in-Project actions automatically. Neither mode weakens Project isolation, session binding, human management authority or audit.
- **Protocol:** first-party commands/results/events share typed Protobuf contracts over native gRPC and WSS adapters; browser UI uses WSS, while MCP modules retain **separate** endpoints and provider-native protocols.
- **Shared:** focused reused contracts and mechanisms have explicit consumers. A target layout does not justify a blanket shared rebuild or copying another owner's persistence implementation.

Current V2 source remains transitional: **hands/** and **services/** contain runtime code, **shared/** contains common packages, while the target **infrastructure/** root is not yet populated in this checkout. Preserve existing deployed state, exact approved Development scope and mandatory phase/quality controls during future migration.
