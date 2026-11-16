# ADR 0002: Dedicated Terminal service proposal

**Status: Superseded by the V1 Server Hand.**

## Historical context

Earlier architecture proposals separated a `/terminal/mcp` runtime with persistent workspace/home volumes, bounded synchronous commands, interactive jobs and cursor-based logs. The durable-job model was valuable, but a standalone Terminal MCP is not the implemented V1 component boundary.

## Current decision

The Server Hand owns **both file and terminal capabilities** at `/server/mcp`. It provides bounded exec, long-running and PTY jobs, cursor-addressed output, cancellation, retained job metadata and the persistent shared workspace. There is no separate Terminal, Files or Curl MCP service. Job records/logs and workspace files have separate lifecycle and retention; cleanup must not delete agent repositories.

## Consequences

Do not create a separate `terminal` Coolify resource or route, or treat `projects/<workspace-id>/repo` as the canonical Git layout. Use one repository-named folder under `/workspace/projects`, then linked worktrees for concurrent agents.

See [Server Hand](../hands/server.md), [workspace policy](../operations/git-and-worktrees.md), [source](../../services/hands/server/README.md).
