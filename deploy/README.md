# V1 deployment entrypoints

**Current deployment guide:** [`docs/operations/deployment.md`](../docs/operations/deployment.md).

For specific tasks:

- [Node configuration and secrets](../docs/operations/configuration.md).
- [Database, migrations and rollback](../docs/operations/database-and-recovery.md).
- [Validation and live acceptance](../docs/operations/testing.md).
- [Services](../docs/services/README.md) and [Hands](../docs/hands/README.md).
- [Generated service catalog](services.json) and [MCP Compose template](templates/mcp-service.yaml).

Briareus V1 deploys **four independent core resources** and up to **eleven independently deployed Hands**, defined by `deploy/services.json`. Each owner has `docker-compose.yaml` and `docker-compose.coolify.yaml`. A source update does not modify Coolify's saved Watch Paths or configuration automatically. The required external OIDC provider and native Ghidra MCP are not part of Dependencies.

## Local developer commands

```sh
python scripts/briareus_catalog.py --check
python scripts/briareus_dockerfiles.py --check
uv run --frozen --no-env-file --group quality python scripts/briareus_coolify.py --check
python scripts/briareus_local.py status
```

The local launcher also supports `init`, `build`, `up` and explicitly selected owner resources. It uses the existing persistent development volumes and local-only configuration; do not run a second owner against the same physical volumes. Its optional ZITADEL test fixture is separate from production and requires explicit invocation.

Root `uv.lock` is for aggregate development and quality checks. Production images use service-owned frozen locks. Choose `BRIAREUS_TEST_DATABASE_BACKEND=sqlite` for lightweight local validation; the default deployed API database is PostgreSQL with Alembic.

**Do not use** the historical single-application `deploy/coolify` files as V1 instructions; the old `legacy-mcp-bridge` branch is retired. Keep real database, browser profile and workspace volumes intact across rollouts. Verify the exact target node, protected secret references, generated parser/Watch Path settings, ready state and authenticated consumers before claiming deployment acceptance.
