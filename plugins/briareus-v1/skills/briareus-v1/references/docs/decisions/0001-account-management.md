# ADR 0001: Legacy Management SQLite ownership

**Status: Superseded by Briareus V1 independent Control Panel API.**

## Historical context

The old MCP Bridge bundled a private Management runtime with encrypted provider accounts in SQLite. Its design separated provider credentials from GitHub/GitLab runtime processes and required an explicit `account_id` for access. That principle remains useful, but the standalone Management process and its migration-free schema ownership no longer exist in V1.

## Current decision

The **Control Panel API** owns account and credential persistence, invocation audit, configuration and Files administration. It defaults to PostgreSQL with versioned Alembic schema changes. SQLite is available only when explicitly selected for local/test usage. Provider Hands cannot open the API database; they resolve the selected account through authenticated internal calls. Existing provider credentials are encrypted at rest.

## Consequences

Do not create a `management` service, revive `/management` or reset application tables on schema mismatch. No old Management password/session is accepted as external OIDC identity. Public API access requires verified issuer/audience/node-role authorization.

See [Control Panel ownership](../services/control-panel.md), [database/recovery](../operations/database-and-recovery.md), [source](../../services/control-panel/api/README.md).
