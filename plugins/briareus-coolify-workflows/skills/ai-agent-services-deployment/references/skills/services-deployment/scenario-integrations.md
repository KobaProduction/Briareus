# Scenario: External Integrations without ENV Sprawl

Load when an application connects to an externally operated API, S3-compatible bucket, mail relay, OAuth provider or telemetry backend. The main decision is **who operates each value**, not which variable can be added. Consult `integration-variables.md`, `credential-variables.md`, `variable-glossary.md`, `environment-policy.md` and `coolify-secrets.md` only for relevant keys.

## Ownership matrix

| Parameter | Usual owner | Deployment action |
| --- | --- | --- |
| External immutable endpoint / tenant required for startup | Infrastructure operator | Required Resource or scoped Shared input when not derivable |
| S3 endpoint / bucket / region | Infrastructure or application's storage owner | Use approved `S3_*` inputs **only** where independently configured |
| S3 access key / secret key | External IAM/Secret Manager | Static credentials only if workload identity is unavailable |
| SMTP host / port / authentication | Transport owner; alternatively application admin UI | Expose `SMTP_*` only where deployment owns transport |
| Public OAuth issuer/client ID | Product identity/integration owner | External URL/ID only if needed by runtime and not configured through app UI |
| OAuth client secret / static API key / bearer token | Provider's secret authority | Protected reference, never pasted into Compose, File Mount or CI logs |
| User OAuth access/refresh tokens | Application database/token store | Dynamic state, **not** standing deployment ENV |
| Poll interval, feature UI options, customer-specific OAuth connections | Application/admin UI | Do not force into ENV just because the code can read it |

Examples from the approved glossary: `S3_ENDPOINT` is Required for an independently operated S3-compatible target, **not** when the SDK discovers AWS S3 itself; `S3_ACCESS_KEY` and `S3_SECRET_KEY` are absent when the platform provides a scoped IAM role. For SMTP, `SMTP_PORT=587` is a STARTTLS default only if that transport is genuinely deployment-owned; use `465` with implicit TLS where the provider requires it. Neither port should be silently paired with plaintext credential fallback.

## Integrate one service

1. Identify the external **consumer** and the actual upstream SDK or image variables. Reuse its existing contract first. If a short operator-facing `S3_*` / `SMTP_*` / `OTEL_*` key is agreed, map it once to the upstream name; never expose both as independent operator fields.
2. Classify input as Required, approved default, stable Compose literal, protected Shared secret, or application-owned state. Avoid redundant full connection URL plus decomposed fields unless different consumers truly need both. No automatic creation of every key listed in the glossary.
3. Select the narrowest real Team/Project/Environment/Resource scope; a Shared key needs an **unambiguous owner** when several resources use the namespace. A deployment-environment suffix is exceptional when scopes cannot separate prod/dev. Keep secret values in the approved external manager or protected provider.
4. In Git, publish **references and names only**. If Coolify must materialize variables, use `${NAME:?}` for genuinely Required operator inputs; `${NAME:-safe}` only for a justified default. Repeat `environment:` under Coolify's `extends` entrypoint when parser discovery needs it. Reconcile resource flags (Runtime vs Buildtime) and exact Shared reference metadata without revealing values.
5. Verify service-specific behavior through its consumer (authorized bucket operation, mail delivery via the expected transport, OAuth callback, authorized API response) and keep the result in the **owning service runbook**. Universal skill is not a service test suite. Credential rotation, external provider migration and OAuth client changes need operator-approved cutover.

## Avoid these anti-patterns

- One generic `API_TOKEN` or `APP_SECRET` for several independent providers; use purpose-specific `*_API_KEY`, `*_BEARER_TOKEN`, `*_CLIENT_SECRET`, `*_SIGNING_PRIVATE_KEY` only where applicable.
- Storing access/refresh tokens that rotate per user/session as static Coolify ENV.
- Passing literal secret content through edit-friendly Coolify `content:` File Mounts; a reference such as Alloy `sys.env("NAME")` must be resolved **by the process**, not assumed expanded by Coolify.
- Replacing existing Shared values, generating new secret identities or renaming live variables without explicit operator agreement.

The completion criterion is a minimal approved operator keyset, one secret authority per actual credential and a verifiable consumer path; more environment fields are not a success metric.
