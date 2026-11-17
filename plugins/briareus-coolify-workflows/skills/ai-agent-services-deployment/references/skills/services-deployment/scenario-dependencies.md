# Scenario: One Stack for Stable Dependencies

Load when PostgreSQL, optional PgBouncer, Valkey or other external dependencies have one operational owner and change much less often than the application. Load `deployment-runtime.md`, `pgbouncer-deployment.md` if used, `variable-glossary.md` for new keys, and `coolify-compose.md` when Coolify parses the resource.

## Decision and files

A single `deploy/dependencies/` directory may contain one Docker Compose **resource** with multiple Compose services, plus a single system README at `deploy/README.md`:

```text
deploy/
  README.md
  dependencies/
    docker-compose.yaml
    docker-compose.coolify.yaml
    config/pgbouncer.ini       # only if pooler is actually selected
    bootstrap/                # only if initialization is necessary
```

No requirement to create a Coolify resource per database, pooler, admin UI or cache. Split when lifecycle/security/rollback/migration needs justify it. First choose state ownership and backups; Valkey state is not PostgreSQL state, and PgBouncer must not inherit PostgreSQL's data volume. Only image/config changes in this unit should trigger its deployment; backend source changes should not, unless they genuinely alter a consumed shared contract.

## PgBouncer behind a stable address

Choose one of these mutually exclusive targets **on the same actual private network**:

| Unit contains | `database:5432` resolves to | Direct DBA/migration route |
| --- | --- | --- |
| PostgreSQL only | PostgreSQL service | `postgres:5432` |
| PostgreSQL + PgBouncer | PgBouncer service listening on 5432 | `postgres:5432` |

The `database` alias belongs to one service **only**. The PostgreSQL container always listens on `5432`, so the host port is not changed. If PgBouncer is enabled, its native `listen_port` changes from the usual `6432` to `5432` **inside its own container**; it forwards to `postgres:5432`. Ordinary backend connection strings do not change when the pooler is toggled. Configuring host port bindings for both is unnecessary and can create conflicts.

Schematic fragment for the **PgBouncer-enabled** variant (not a complete secure runnable stack):

```yaml
services:
  postgres:
    image: postgres:18
    environment:
      POSTGRES_USER: ${POSTGRES_USERNAME:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?}
      POSTGRES_DB: ${POSTGRES_DATABASE:-postgres}
    volumes:
      - postgres-data:/var/lib/postgresql
  pgbouncer:
    image: <verified-pooler-image>
    networks:
      default:
        aliases: [database]
    # config/pgbouncer.ini and auth must be supplied by that image's contract
volumes:
  postgres-data: {}
```

Do not paste this fragment into production: `<verified-pooler-image>` is a design placeholder, and the actual image's config, password/ACL mapping, PostgreSQL volume location, checks and privileges must be resolved. **Without the pooler**, put `networks: default: aliases: [database]` on `postgres`, not on both. On multi-resource Coolify deployments, verify that the alias propagates on the real predefined network before promising transparent resolution.

## Configuration and acceptance

- `POSTGRES_USERNAME` default `postgres`; `POSTGRES_DATABASE` default `postgres`; `POSTGRES_PASSWORD` protected Required. Do not create extra app roles or `PGBOUNCER_*` ENV automatically. If an approved separate account exists, use scoped names and bootstrap its privileges.
- Keep `pgbouncer.ini` as tracked config or Coolify File Mount via `content:` when operators must edit it. Prefer native `session` pooling initially; use `transaction` only after verifying driver/session behavior. Do not imply that the pooler can handle every workload transparently.
- Valkey uses agreed `VALKEY_USERNAME`, `VALKEY_PASSWORD`, and optional `VALKEY_DATABASE` on client side; its image must actually configure ACL/auth. Never make cache startup accidentally provision a universal insecure open listener.
- Gate backend **readiness** on actual database reachability and completed bootstrap, not just an open socket. Do not use ordinary Compose `depends_on` across separate Coolify resources. Keep PostgreSQL backups and recovery separate from pooler restart.
- Acceptance: from backend network resolve `database`, authenticate and run a query through the selected path; verify direct DBA path, reconnect/restart, secrets and volume identity; when pooler is enabled, prove no duplicate `database` alias and measured pool compatibility. Do not redeploy live PostgreSQL without explicit approval.
