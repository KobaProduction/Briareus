# Optional PgBouncer as PostgreSQL Client Endpoint

Load when a deployment uses PostgreSQL and its architecture includes or considers PgBouncer. A pooler is **optional**, not one resource per container and not a mandatory prerequisite for all PostgreSQL services. Reuse the existing PostgreSQL/credential contract; do not automatically create extra PgBouncer logins, ENV fields or Secret Manager keys.

## Stable application-facing endpoint

Prefer one service-DNS endpoint for ordinary application connections: `database:5432`. Use a network-local alias **owned by exactly one endpoint at a time**:

- **With PgBouncer:** PgBouncer answers at `database:5432`; its `[databases]` forwards to `postgres:5432` on the same private application network. Set `listen_port = 5432` explicitly in `pgbouncer.ini` (PgBouncer's standard is `6432`); PostgreSQL still listens internally on its usual `5432`.
- **Without PgBouncer:** assign `database` to PostgreSQL, which answers at its ordinary `5432`. Applications keep the same hostname, port, database and user inputs. Do not assign `database` to PostgreSQL and PgBouncer simultaneously.
- Prefer service aliases on **environment-isolated networks**, not global container names or exposed host ports. If Coolify resources are independent, verify the actual shared Docker network and alias resolution. Do not assume Compose-local DNS or aliases propagate across unconnected resources.
- Migrations, backups, administration and clients that require a direct session use `postgres:5432` where justified and authorized. Do not expose the direct PostgreSQL port publicly merely to bypass the pooler. A pooler cutover still requires verified connection behavior, compatible auth and rollback; an unchanged DNS name alone is not proof of transparent semantics.

## PgBouncer configuration (mostly literals, not obligatory ENV)

| Optional operator key | Native `pgbouncer.ini` setting | Default/decision |
| --- | --- | --- |
| `PGBOUNCER_POOL_MODE` | `pool_mode` | `session` is upstream default; `transaction`/`statement` only after driver/session compatibility review |
| `PGBOUNCER_DEFAULT_POOL_SIZE` | `default_pool_size` | Upstream default `20` |
| `PGBOUNCER_MAX_CLIENT_CONNECTIONS` | `max_client_conn` | Upstream default `100`; account for file descriptors |
| `PGBOUNCER_AUTH_TYPE` | `auth_type` | Set from the approved authentication contract; no universal insecure fallback |
| `PGBOUNCER_LISTEN_PORT` | `listen_port` | For this transparent pattern use **literal `5432`**; only expose an ENV if an operator truly changes it |

Use an ordinary tracked or Coolify-managed `pgbouncer.ini` when settings are stable. The upstream PgBouncer binary does **not** consume these custom ENV names directly; an image-specific template/entrypoint must implement any approved mapping. `auth_file`/`auth_query` and PostgreSQL credentials remain separate actual configuration decisions; don't create duplicate `PGBOUNCER_USERNAME`/`PGBOUNCER_PASSWORD` by default. Preserve durable PostgreSQL storage and bootstrap ordering; healthcheck/readiness applies to both long-running services where supported.

Source: [PgBouncer configuration](https://www.pgbouncer.org/config), [Docker Compose network aliases](https://docs.docker.com/reference/compose-file/services/#aliases).
