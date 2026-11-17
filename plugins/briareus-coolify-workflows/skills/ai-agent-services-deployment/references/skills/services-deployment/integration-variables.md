# S3 and SMTP Variable Contracts

Load when designing **S3-compatible object storage** or **SMTP** operator inputs. Naming and scope → `variable-glossary.md`; Required/default and parser semantics → `coolify-variables.md`; secret management → `coolify-secrets.md`. These are approved **operator names**, not necessarily upstream SDK/image ENV. Introduce each field only if the owning resource needs an operator input. A new key or a migration still needs operator approval; do not rewrite live settings automatically.

## S3-compatible object storage

| Canonical name | Required/default | Upstream/ownership |
| --- | --- | --- |
| `S3_ENDPOINT` | Required for a configurable non-AWS endpoint; absent for normal AWS endpoint discovery | Map to SDK endpoint (e.g. `AWS_ENDPOINT_URL_S3` when supported) |
| `S3_BUCKET` | Required if deployment owns bucket selection; otherwise code/config | Bucket name, no universal default |
| `S3_REGION` | Required when chosen provider/SDK needs it | Map to SDK region (e.g. `AWS_REGION`); no invented default |
| `S3_ACCESS_KEY` | Required **only** for static-key authentication | Credential, map to e.g. `AWS_ACCESS_KEY_ID` |
| `S3_SECRET_KEY` | Required **only** with static `S3_ACCESS_KEY` | Protected secret, map to e.g. `AWS_SECRET_ACCESS_KEY` |
| `S3_FORCE_PATH_STYLE` | Optional when provider/client requires path-style addressing | SDK-specific Boolean; do not expose otherwise |

Prefer IAM roles, workload identity or SDK credential discovery over static keys when supported. Never expose redundant AWS and S3 operator variables for the same credential. A variable declaration does not create a bucket, grant access or configure lifecycle rules. Public object/CDN URL belongs to its real consumer, not automatically to `S3_ENDPOINT`. In a shared scope qualify owner only when otherwise ambiguous.

## SMTP delivery

| Canonical name | Required/default | Contract |
| --- | --- | --- |
| `SMTP_HOST` | Required when deployment owns SMTP transport | External relay hostname, no universal default |
| `SMTP_PORT` | Default `587` **with STARTTLS** only | `465` is normally implicit TLS; select coherently |
| `SMTP_USERNAME` | Required when using SMTP username/password authentication | No universal default |
| `SMTP_PASSWORD` | Required only with password-based SMTP AUTH | Protected secret, no default |
| `SMTP_FROM_ADDRESS` | Required if deployment owns sender identity | Authorized sender address; no invented default |
| `SMTP_FROM_NAME` | Optional when operator controls display name | Prefer app UI if app owns it |
| `SMTP_TLS_MODE` | Optional when transport/security mode needs an operator override | E.g. `starttls` / `implicit_tls` mapped to actual client settings |

Do not force password ENV for an approved internal relay without SMTP AUTH or for OAuth-based authentication. Do not silently fall back to plaintext authentication. Keep SMTP provider settings in an application admin UI when that UI is already authoritative. Do not externalize sender display or client tuning as ENV without an operator use case.

## Scope boundary

PgBouncer is addressed in `pgbouncer-deployment.md` only when the PostgreSQL stack needs an optional pooler. This S3/SMTP table does not change database routing.

Upstream references: [AWS SDK settings](https://docs.aws.amazon.com/sdkref/latest/guide/settings-reference.html), [SMTP transport](https://nodemailer.com/smtp), [PgBouncer configuration](https://www.pgbouncer.org/config).
