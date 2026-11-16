# Briareus — Infrastructure / Hands / focused Shared packages

## Mandatory engineering rules

Before any implementation/refactoring, every agent MUST read [Briareus Clean Architecture / DDD adoption](docs/architecture/clean-architecture-ddd-briareus.md), the linked [AI Agent Workflow reference](docs/architecture/ai-agent-workflow/clean-architecture-ddd.md), and [local quality policy](scripts/quality/README.md). These apply to ALL first-party services, MCP Hands, shared libraries and UI; no per-service opt-in.

**Refactoring tool priority:** Prefer working semantic inspection and refactoring tools built into the current environment, editor, IDE or Codex. Use Serena MCP only as a fallback when the required native tools are absent, unavailable or not working. Check the capabilities actually exposed in the current session; do not assume a native refactoring tool exists. Do not start or keep Serena/LSP processes running when native tools cover the work. When the fallback is needed, use Serena with the appropriate Python/TypeScript/Vue LSPs and obey the singleton rule below.

**Serena singleton:** At most ONE Serena MCP server instance is allowed for the entire Briareus project, across all chats and agents. Reuse the existing project server and its Python/TypeScript/Vue LSPs; do not start a server per chat, agent, service, or task. Before starting Serena, verify that no project instance already exists. If a client cannot reuse the existing connection, report that limitation instead of spawning a duplicate. For STDIO clients that cannot share a connection, only the designated owner invokes Serena; other agents request semantic inspection from that owner instead of initializing their own connection. Report client-side automatic duplicate startup rather than repeatedly reconnecting or starting another server. Reconnect to or restart the single instance only when it is unavailable, coordinating with its current owner to avoid disrupting active work.

Domain owns invariants and typed entities/value objects; application owns use cases and ports; infrastructure owns storage/provider/process implementations; presentation adapts existing HTTP/WebSocket/gRPC/MCP contracts. Dependencies point inward. Frontend retains FSD, entity models and shared UI with no cross-slice implementation imports. No framework/ORM/network/process dependencies inside domain, no service-to-service persistence imports, no business orchestration inside routers/components.

Owner quality contract: cognitive complexity <=15 in production and <=30 in tests; no Any or untyped Python functions; no ordinary dictionary result contracts (use dataclass/NamedTuple/typed models). Do not weaken gates, add blanket ignores or preserve a duplicate implementation to make checks pass. Architectural extraction must preserve authority, runtime isolation, event ordering and idempotency; no speculative schema reset, protocol change or new pattern without a real invariant. Publication follows the local-validation and coherent-batch contract below, not a blanket push prohibition.

Parallel agents own disjoint files/modules, coordinate shared contracts through the root agent and direct peer messages, and never revert peer edits. No new local task/backlog/report Markdown; report progress in chat and keep machine diagnostics under ignored artifacts/. Current owner scope excludes CI changes, shell/Docker/Compose lint expansion, third-party code changes and deferred feature expansion. Complete foundation/source work across ALL owners before the separate later test phase. Scoped Biome/Ruff/mypy/type diagnostics are allowed as needed during source work. Remove incompatible legacy implementations and obsolete compatibility paths after resolving actual consumers; retain useful mechanisms with their correct owner. Delete tests exclusive to removed/incompatible legacy contracts, not tests exposing current defects or preserving applicable invariants. Do not run, write or adapt new/retained tests or fixtures during this source phase; diagnostic tests and per-block acceptance are not exceptions. No broad frontend refactor belongs to this cleanup. Test/fixture adaptation and final aggregate acceptance begin only in the separately authorized next phase after all owners finish their source work. Do not run tests/builds after every function or extraction. Mandatory quality hooks remain enabled.


## Mandatory owner-specific policies

The following pages contain the binding V2 rules formerly embedded in this root file.
**Read every relevant owner page before changing source, documentation or deployment**;
changes spanning owners require reading both sides and coordinating the shared contract.

- [Canonical repository and source topology](docs/core/source-topology-policy.md)
- [Infrastructure identity and human management authority](docs/infrastructure/identity-and-human-authority.md)
- [Hands / Node sessions, access and MCP module authority](docs/hands/node-access-policy.md)
- [Hands / Project storage, common files and transfer](docs/hands/storage-policy.md)
- [Shared first-party RPC and resource delivery](docs/shared/rpc-and-delivery-policy.md)
- [Owner coordination and handoffs](docs/operations/source-ownership-policy.md)
- [Publication restrictions and Development resource scope](docs/operations/release-and-scope-policy.md)

Navigation: [documentation index](docs/README.md), [Infrastructure](docs/infrastructure/README.md),
[Hands](docs/hands/README.md), [Shared](docs/shared/README.md), and
[Operations](docs/operations/README.md). Those owner indexes route to the existing
detailed architecture and service contracts rather than replacing them.

Before any implementation, continue to read the mandatory Clean Architecture/DDD
adoption, linked AI Agent Workflow reference and local quality policy named above.
V1 is a separate branch and architecture. The target V2 documentation does not
prove that a source move or runtime cutover has been completed.

The current operator has intentionally stopped Serena; do not start it as part of
documentation or repository organization. Respect the workspace-wide policy
at /workspace/projects/AGENTS.md for canonical project folders and Git worktrees.
