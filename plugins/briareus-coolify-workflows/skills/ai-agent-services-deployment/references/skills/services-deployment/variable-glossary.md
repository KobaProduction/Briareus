# Deployment Variable Glossary

Load when creating or reviewing operator/Shared/secret names; skip for unchanged approved deployments. This owns the names below. Telemetry → `telemetry-variables.md`; parser → `coolify-variables.md`; ENV ownership → `environment-policy.md`; secrets → `coolify-secrets.md`. New keys and migrations need approval.

## Naming and scope

- Operator keys use upper `SNAKE_CASE` and full words (`USERNAME`, `PASSWORD`, `DATABASE`), not `USER`, `PWD`, `DB`. Preserve upstream keys and map at the consumer boundary; avoid aliases.
- Inside a single-resource/single-consumer context, use short names such as `POSTGRES_USERNAME`; the Coolify Resource already identifies the owner. With multiple consumers/identities **within a resource**, or in Shared/Secret Manager scopes spanning resources, prefix the actual owning service: `ZITADEL_POSTGRES_PASSWORD`, `BACKEND_POSTGRES_PASSWORD`. Never publish ambiguous unqualified `POSTGRES_PASSWORD` in a shared namespace.
- Prefer native Team/Project/Environment/Server scopes to encoding `DEV`/`PROD` in names. Add deployment-environment prefixes/suffixes only when the store cannot separate the values and collision would otherwise occur. A shared key's owner is the *principal or system it configures*, not always the container consuming it.
- For every candidate state purpose, owner/consumer, external input vs derived constant, scope, Required/default, secret status and upstream mapping. Use an existing approved name first. On mismatch **report a proposed mapping/rename; do not mutate live keys or rotate secrets** as part of unrelated work.

## PostgreSQL — one resource, one database context

| Operator key | Coolify contract | Upstream input | Decision |
| --- | --- | --- | --- |
| `POSTGRES_USERNAME` | `${POSTGRES_USERNAME:-postgres}` | `POSTGRES_USER` | Exposed default `postgres`, editable when useful |
| `POSTGRES_PASSWORD` | `${POSTGRES_PASSWORD:?}` | `POSTGRES_PASSWORD` | Required, empty until secret reference is set |
| `POSTGRES_DATABASE` | `${POSTGRES_DATABASE:-postgres}` | `POSTGRES_DB` | Exposed default `postgres` **by agreement**, not literal-only |

`POSTGRES_USER` in the official image creates an initial superuser (not an automatically least-privileged app user). These initialization variables act on a fresh data directory, not as automatic migrations of existing users/databases. Keep the minimum viable single-role bootstrap when explicitly accepted; separate service accounts only when the architecture calls for isolation. Do not force account proliferation on a small deployment.

When the **administrator identity is explicitly separated**, `POSTGRES_SUPERUSER_PASSWORD` identifies that privilege and may map to the upstream initial `POSTGRES_PASSWORD`. Do not expose *both* names for the **same** secret without an approved reason. The administrator username may remain literal `postgres`; qualify an admin key with the owning instance if a wider Shared scope contains several PostgreSQL instances.

## PostgreSQL — multiple consumer principals or wider Shared scope

| Scoped key pattern | Purpose | Placement |
| --- | --- | --- |
| `ZITADEL_POSTGRES_USERNAME` / `ZITADEL_POSTGRES_PASSWORD` | ZITADEL database login | Shared/secret provider when used across resources; owner `ZITADEL` |
| `BACKEND_POSTGRES_USERNAME` / `BACKEND_POSTGRES_PASSWORD` | Backend database login | Separate principal if provisioned |
| `PLATFORM_POSTGRES_USERNAME` / `PLATFORM_POSTGRES_PASSWORD` | Deliberately shared platform login | Only when shared privileges were explicitly accepted |
| `<OWNER>_POSTGRES_DATABASE` | Database owned by that consumer | Default may be in Compose; create ENV only when an override is needed |

Prefix only when ownership is ambiguous. Bootstrap owns database roles, grants and migrations.

## Valkey

| Operator key | Coolify contract | Purpose |
| --- | --- | --- |
| `VALKEY_USERNAME` | `${VALKEY_USERNAME:-default}` | ACL username; default `default` |
| `VALKEY_PASSWORD` | `${VALKEY_PASSWORD:?}` | Required secret; no default |
| `VALKEY_DATABASE` | `${VALKEY_DATABASE:-0}` **if needed** | Client-selected logical database, default `0` |

Use short names for a single Valkey resource; **only qualify the actual owner** in wider Shared/secret scopes or when independent Valkey credentials collide. Do not add redundant `BACKEND_`/`PLATFORM_` prefixes by default. Map operator keys to the image's actual configuration/ACL and consuming client; ENV declarations alone do not provision users. `VALKEY_DATABASE` is optional at deployment level, not a mandatory server setting. No parallel Redis naming contract.

## Other integrations

S3/SMTP → `integration-variables.md`; optional PgBouncer endpoint → `pgbouncer-deployment.md`; credential suffixes → `credential-variables.md` (each on demand). ZITADEL bootstrap is service-specific.
