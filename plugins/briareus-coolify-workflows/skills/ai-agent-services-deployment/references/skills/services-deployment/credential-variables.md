# Credential Variable Naming

Load only when choosing or reviewing password/token/key/secret names. Scope and conditional prefixes → `variable-glossary.md`; secret storage and permissions → `coolify-secrets.md`; whether a value belongs in deployment ENV → `environment-policy.md`. This is a naming contract, **not** a reason to create every listed variable. Match purpose and upstream requirements; expose only keys the operator genuinely owns.

| Purpose | Canonical suffix / name | Example | Deployment rule |
| --- | --- | --- | --- |
| Account password | `_PASSWORD` | `POSTGRES_PASSWORD` | Protected Required if independently operated; never default secret |
| API key | `_API_KEY` | `PAYMENTS_API_KEY` | Static integration credential only when SDK/provider requires it |
| Static Bearer credential | `_BEARER_TOKEN` | `OTEL_BEARER_TOKEN` | Store raw token in Secret Manager; synthesize `Authorization: Bearer …` within the supported client |
| OAuth client identifier | `_CLIENT_ID` | `OAUTH_CLIENT_ID` | Public identifier, not automatically a secret |
| OAuth client authentication | `_CLIENT_SECRET` | `OAUTH_CLIENT_SECRET` | Secret Manager, only if this OAuth client uses a secret |
| OAuth access token | `_ACCESS_TOKEN` | `PROVIDER_ACCESS_TOKEN` | Usually acquired/renewed dynamically, **not** a static deployment ENV |
| OAuth refresh token | `_REFRESH_TOKEN` | `PROVIDER_REFRESH_TOKEN` | Usually persistent application state; use protected token store/rotation, not a standing ENV |
| Symmetric encryption key | `_ENCRYPTION_KEY` | `DATA_ENCRYPTION_KEY` | Secret; changing it may make stored ciphertext unreadable |
| Asymmetric signing key | `_SIGNING_PRIVATE_KEY` | `JWT_SIGNING_PRIVATE_KEY` | Secret; keep public verification key separate if needed |
| HMAC signing secret | `_SIGNING_SECRET` | `WEBHOOK_SIGNING_SECRET` | Shared secret used to sign/verify; not the same as a private key |

## Decisions

- Choose the **specific function**, not a generic `SERVICE_SECRET`, `APP_KEY` or `AUTH_TOKEN` when ambiguous. No mandatory resource prefix when its owner is obvious; prefix provider/consumer only for multiple identities or wider Shared/Secret Manager scopes.
- `_TOKEN` alone is acceptable **only** when the protocol/upstream has an established single token purpose; otherwise distinguish bearer, access, refresh, registration or another actual token type. `_KEY` alone is similarly ambiguous; identify API access, encryption, signing or provider-native key where necessary.
- Do not invent `REFRESH_ENCRYPTION_KEY` or any compound key without a real independent secret and approved consumer. OAuth tokens are data with expiry/rotation, not automatically new deployment inputs.
- Preserve established upstream names such as `AWS_SECRET_ACCESS_KEY` or `S3_SECRET_KEY`; do not rename them for style if mapping creates noise. Never alias two ENV values onto one secret unless the consumer truly requires that mapping.
- Secret status is **not** determined by the suffix: a client ID may be public, while an access key identifier may be sensitive in context. Use the approved scope/provider, avoid printing values, and treat key rotation separately from renaming.

This glossary never authorizes automatic creation, migration or rotation of credentials in live deployments. The operator approves each changed contract.
