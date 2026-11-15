# Briareus API validation

Run affected modules from the repository root:

```sh
python tests/run_briareus_contracts.py test_briareus_postgres test_briareus_panel_tokens test_briareus_api_routes test_briareus_api_state
```

Service-local behavior belongs here. Cross-service proxy and WebSocket authority contracts live in `tests/integration/contracts`. The test authority generates an isolated RSA key and supplies external JWKS in memory; no local user session database or production identity provider is involved.

## Database backends

The Control Panel API uses PostgreSQL in production by default. For local
validation and lightweight development, explicitly choose SQLite:

```sh
CONTROL_PANEL_DATABASE_BACKEND=sqlite
CONTROL_PANEL_SQLITE_PATH=/tmp/briareus-control-panel-test.sqlite3
```

`CONTROL_PANEL_SQLITE_PATH=:memory:` also works for a single-process fixture.
For SQLite, `POSTGRES_PASSWORD`, `POSTGRES_USERNAME` and `POSTGRES_DATABASE`
are not required. The parent directory of a SQLite file must already exist.
Database startup uses the same SQLAlchemy repository layer and Alembic revisions;
revision `0002` uses SQLite batch operations instead of PostgreSQL-only
`ALTER COLUMN`. There is no silent driver fallback.

To select PostgreSQL, leave `CONTROL_PANEL_DATABASE_BACKEND=postgresql` (the
default) or set it explicitly. Configure `POSTGRES_HOST`, `POSTGRES_PORT`,
`POSTGRES_USERNAME`, `POSTGRES_PASSWORD` and `POSTGRES_DATABASE` as needed.
The production default is unchanged. SQLite is **not** a drop-in replacement for
PostgreSQL's advisory locks, high-write concurrency or transaction guarantees;
do not switch a deployed production database without a separate data-migration
plan and acceptance.

The migration test entrypoint accepts `BRIAREUS_TEST_DATABASE_BACKEND=sqlite`
(the default), `postgresql`, or `both`:

```sh
uv run --frozen --no-env-file python services/control-panel/api/tests/integration/postgres_migrations.py
BRIAREUS_TEST_DATABASE_BACKEND=both BRIAREUS_TEST_POSTGRES_MODE=native \
  uv run --frozen --no-env-file python services/control-panel/api/tests/integration/postgres_migrations.py
```

The default SQLite run tests real Alembic upgrades/downgrades, schema checking,
persisted encrypted accounts, retention and failed upgrades without any Docker
or PostgreSQL installation. The advisory-lock concurrency test is PostgreSQL-
specific and is marked skipped for SQLite, not falsely passed.

For PostgreSQL checks, `BRIAREUS_TEST_POSTGRES_MODE=native` starts an isolated
local process on a private Unix socket when `initdb` and `pg_ctl` are installed;
`BRIAREUS_TEST_PG_BIN_DIR` selects their directory. `external` requires an
explicit test-only administrator database named `briareus_test_admin`,
`BRIAREUS_TEST_POSTGRES_URL`, and `BRIAREUS_TEST_POSTGRES_ALLOW_CREATE=1`;
it creates/drops only uniquely named test databases. Never point it at an
existing production database. Docker remains optional via the explicit `docker`
mode. The JSON report records both `sqlite_migration_coverage` and
`postgres_coverage` independently.
