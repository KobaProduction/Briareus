# V1 status, acceptance and future work

This page tracks the **current V1 direction**. It is not the previous MCP Bridge backlog.

## Established in source

- Four independently deployed core applications, eleven optional Hands in the catalog and per-owner Compose/locks.
- External OIDC authentication/resource verification and node-role access contract; API/Gateway own different surfaces.
- Provider accounts, encrypted credentials and audit in Control Panel API.
- Server Hand combines workspace files, terminal execution and persistent jobs; Playwright owns internal/external browser modes.
- Shared capability libraries, discovery and explicit build/Watch Path dependencies.
- PostgreSQL/Alembic default plus explicitly selectable SQLite local/test backend.

These are statements about source/contracts; they do not certify every possible service is currently deployed or all consumer flows accepted.

## Acceptance and maintenance

- Test changes with relevant owner suites and the [aggregate gate](operations/testing.md) at the review boundary.
- Verify real Coolify saved configuration, node-specific persisted volumes, provider authorization, OIDC browser renewal, CDP health, native analysis backends and authenticated MCP operations.
- Keep expected stopped services (currently Serena) distinguished from unexpected failures.
- Maintain docs by owner domain and verify links/service counts when catalog or runtime changes.
- Track active issues through GitHub rather than generating a parallel Markdown backlog.

## Separate architecture

`v2` has autonomous Nodes, local Projects, Cedar/session approvals and binary control-channel architecture. These requirements belong on the `v2` branch; no V1 documentation authorizes a silent V2 cutover. Old Management/Curl/legacy multi-container topology descriptions belong only in [historical context](https://github.com/KobaProduction/Briareus/blob/v1/docs/history/README.md).
