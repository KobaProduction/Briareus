# Repository and documentation ownership — V1

## Code

| Path | Responsibility |
| --- | --- |
| `services/control-panel/ui` | Static Vue SPA; its own Compose, build context, UI tests |
| `services/control-panel/api` | API, encrypted provider accounts, PostgreSQL/SQLite adapters and Alembic |
| `services/gateway` | Public routing, token verification, MCP/resource metadata |
| `services/dependencies` | Third-party PostgreSQL, Valkey, Chromium and their lifecycle |
| `services/hands/<owner>` | Independently built/deployed MCP Hands (see source catalog) |
| `shared/<capability>` | Narrow reused contracts/policies/transports with explicit consumers |
| `deploy/services.json` | Source of truth for deployable resources and Watch Paths |
| `deploy/templates` | Shared MCP Compose inputs |
| `tests/` | Cross-owner contracts, fixture code and validation |
| `scripts/` | Catalog generators, local launcher and quality checks |

There is no standalone Management source owner, independent Curl MCP, root `bridge` runtime or central `common` application package. Each Python service builds from its own frozen manifest and copies only required shared packages.

## Documentation

- `docs/core/`: system rules and runtime boundaries.
- `docs/services/`: Control Panel UI/API, Gateway, Dependencies.
- `docs/hands/`: one page per MCP Hand family, pointing to service-local READMEs.
- `docs/operations/`: deployment, persistence, validation and workspace practices.
- `docs/decisions/`: current decisions and explicitly superseded ADRs.
- `docs/history/` and `docs/refactoring/`: older context **not** authoritative for current deployment.

## Workspace policy

A repository under the Server's `/workspace/projects` has one canonical directory named after the repository (`briareus`). Parallel agents use linked Git worktrees in that checkout's ignored `.worktrees/`. A Server workspace ID is a command/job execution context, not an invitation to create duplicate clones. Read `/workspace/projects/AGENTS.md` on the target server and [the V1 Git guide](operations/git-and-worktrees.md).

Generated Watch Paths contain the owning directory and only actually imported shared leaf directories; avoid blanket shared watches and root-wide rebuilds. Actual saved Coolify Watch Paths must be checked separately.
