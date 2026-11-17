# Database, lifecycle and recovery — V1

## PostgreSQL versus SQLite

Control Panel API owns account/configuration/audit application data. Its default production backend is **PostgreSQL** with SQLAlchemy, psycopg and versioned Alembic. An explicit `CONTROL_PANEL_DATABASE_BACKEND=sqlite` with `CONTROL_PANEL_SQLITE_PATH` provides a supported lightweight **local/test** database through the same repository and migration layer. No implicit fallback occurs when PostgreSQL fails.

SQLite contract tests do not prove PostgreSQL advisory locking, concurrency or migration acceptance. Consult [API test backends](https://github.com/KobaProduction/Briareus/blob/v1/services/control-panel/api/tests/README.md) and [validation](testing.md) for exact test modes.

## Schema updates and rollback

The API applies Alembic revisions before serving. Schema changes must be reviewed and tested on fresh and existing data before deployment. An incompatible unversioned schema or failed revision must fail closed, not silently reset persistent tables. Never stamp an arbitrary database version merely to start a container.

Back up the production PostgreSQL database and preserve the configured encryption key/other protected secrets before an incompatible schema change. Reverting the application image does not reverse a migration; plan a reviewed forward fix or an explicit data restore. Existing physical volume names remain stable during node or Coolify resource renames.

## Runtime state

Server jobs and their logs have a separate retention policy from workspace files. A job-log cleanup must **never** remove source workspaces or another agent's active process. The Browser profile is distinct from downloads and can contain authenticated state. Native Ghidra project storage remains separately owned. Shared Valkey caches/discovery leases are not the authoritative durable account store.

See [Server](../hands/server.md), [Dependencies](../services/dependencies.md), [deployment](deployment.md).
