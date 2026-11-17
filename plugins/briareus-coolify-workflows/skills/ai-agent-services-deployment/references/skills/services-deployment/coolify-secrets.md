# Coolify Secrets and Shared Configuration

Load for Shared Variables, protected credentials, external secret providers and agent visibility. Prefer a supported secret manager (such as Infisical), with narrow per-resource permissions, where available. Store confidential values outside Git and agent-readable Resource ENV; **the reference is not the secret**. Verify the provider integration for the deployed Coolify release before prescribing a particular interpolation syntax or assuming agent isolation. One resource may be constrained to one secret-manager source. Shared Variables remain useful for non-secret team/project/environment state and where required by approved integration.

Generate required credentials through an approved restricted setup path and store them in the secret manager; do **not** use parser-generated `SERVICE_PASSWORD_*` / `SERVICE_USER_*` resource variables for credentials. Generated `SERVICE_FQDN_*` / `SERVICE_URL_*` domains remain allowed. Never generate or paste plaintext secrets into agent-visible deployment files or logs.

Secret-manager separation reduces accidental viewing, but is not a hard boundary against an agent that can change deployment code or read process environment. Restrict deploy authority, access to reveals/logs, and secret scopes.

## Secrets and shared variables

Never commit secret values to Compose, Dockerfiles, tracked env files or generated config.

Use the narrowest Coolify shared-variable scope that matches ownership:

- `{{team.NAME}}`
- `{{project.NAME}}`
- `{{environment.NAME}}`
- `{{server.NAME}}`

For a **VictoriaMetrics-owned backend** referenced by multiple resources on Git-backed Coolify 4.3.23, use a two-step example (scope `team` only if actually approved for those consumers):

```yaml
environment:
  VICTORIA_METRICS_URL: ${VICTORIA_METRICS_URL:?}
  VICTORIA_METRICS_AUTH_USERNAME: ${VICTORIA_METRICS_AUTH_USERNAME:?}
  VICTORIA_METRICS_AUTH_PASSWORD: ${VICTORIA_METRICS_AUTH_PASSWORD:?}
```

Then set the generated resource variables in Coolify to the shared references:

```text
VICTORIA_METRICS_URL={{team.VICTORIA_METRICS_URL}}
VICTORIA_METRICS_AUTH_USERNAME={{team.VICTORIA_METRICS_AUTH_USERNAME}}
VICTORIA_METRICS_AUTH_PASSWORD={{team.VICTORIA_METRICS_AUTH_PASSWORD}}
```

Rules:

- verify that the referenced shared variable exists at the exact scope and exact key before deployment;
- do not treat `is_shared=true` on a resource variable as proof that resolution succeeded;
- an unresolved shared reference can remain literal and reach the container, so validate the runtime value indirectly through application behavior/logs without printing secrets;
- on versions where direct `{{scope.KEY}}` inside Git Compose has not been proven, do not hard-code shared references as service environment values; prefer `${VAR}` in Git and put the shared reference in the Coolify resource variable;
- choose the scope that protects secret ownership and visibility while covering authorized consumers;
- an agent usually needs variable names, scopes and references, not plaintext values;
- never reveal or log secret values merely to verify that the reference exists;
- absence of a required shared reference is a deployment/configuration error, not a reason to hard-code a temporary credential.

### Required state is not an unset-value diagnosis

Coolify's **Required** flag describes a configuration obligation; it may remain visible after the value is supplied. Likewise a name-only API returning `is_shared=false` proves neither that the variable is empty nor that its content is correct; `is_shared=true` does not prove the reference resolved. When the user says Shared credentials already exist, read the exact current scope and key metadata, preserve them and configure only the Application reference. Never guess `{{project.KEY}}` versus `{{environment.KEY}}` from a project name or a previous example, invent undocumented `{{scope.name}}` magic properties, recreate existing Shared entries, or replace an owner-scoped principal with a general database administrator just to make startup pass. Validate resolution without revealing secrets.
