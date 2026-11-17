# Coolify / Docker Compose Contract

**Mandatory when Coolify parses, owns or deploys Docker Compose.** This is a parser/runtime contract, not generic Docker Compose documentation: valid Compose YAML can still generate incorrect ENV, routes, storage or managed files in Coolify.

Load additional modules **when their condition applies**:
- Creating/changing resource ENV, Required/default flags or names → `coolify-variables.md`; deciding whether ENV belongs at deployment time → `environment-policy.md`.
- Shared or secret-manager references, secret permissions → `coolify-secrets.md`.
- Cross-resource networks, ingress routes or managed domains → `coolify-networking.md`.
- Managed configuration files, storage and telemetry collector → `coolify-files.md`.
- Existing resource migration, stale parser state or persistent-volume changes → `coolify-migrations.md`.
- Fresh parser/deploy/acceptance checks → `coolify-validation.md`; basic container healthcheck policy → `deployment-runtime.md`.
- Git folders and Watch Paths → `deployment-layout.md` and `git-backed-infrastructure.md`.

## Git-backed inheritance

Use `docker-compose.yaml` (standalone) and `docker-compose.coolify.yaml` (Coolify entrypoint); always `.yaml`. Live Coolify deployments have used `extends` and materialized a managed file, but parser versions and features vary:

```yaml
services:
  app:
    extends:
      file: ./docker-compose.yaml
      service: app
```

- Keep ordinary runtime topology in the generic base. `extends` merges a **service**, not its top-level `volumes:`, `networks:`, `configs:` or `secrets:`; redeclare consumed resources in the entrypoint.
- Repeat Required/default variable interpolation in the entrypoint service `environment:` when inherited declarations are not parser-visible. Do not rename operator keys without approval.
- For Coolify-managed files, repeat the `type: bind` mount with `content:` in the entrypoint if inheritance hides parser metadata. Verify equality of duplicated inline content; prefer one tracked config file where feasible. Coolify `content:` is **not portable generic Compose**. Repository file binds may require **Preserve repository** in Coolify.
- Set Base Directory to the service folder, Compose Location to `/docker-compose.coolify.yaml` relative to it, and Watch Paths to the folder plus consumed shared paths. Verify each resource's saved Watch Paths.
- Validate generic Compose independently; inspect Coolify-parsed ENV, managed files, top-level resources and Deployable Compose. Finished deployment/container presence do not prove consumer behavior. Do not redeploy to diagnose an unapproved parser change.

`include`, command-line multi-file overrides and `extends` have different semantics; do not substitute one without a version-specific parser test.

## Authority

Keep these layers distinct:

1. **Git Compose** — desired topology, non-secret defaults, parser directives, shared-variable references and managed-file templates.
2. **Coolify** — resolved runtime variables, shared-variable values, domains/certificates, parsed persistent storage and deployment lifecycle.
3. **Container runtime** — actual containers, networks, volumes and mounted files.
4. **Acceptance** — real service behavior.

When parser behavior matters, inspect the deployed Coolify version's parser/source instead of assuming generic Compose behavior.

## Mandatory deployment contract

- **Operator approval:** Discuss alternatives without changing Compose, ENV contracts or live resources. Apply only changes the operator explicitly requests; proposals and requests to explore options are not approval to implement them. Obtain agreement before adding, renaming or removing operator keys.
- Prefer existing approved or upstream names. Do not invent prefixes, duplicate credentials, intermediary aliases or new privileged identities for convenience.
- Keep a single canonical Compose owner and only justified orchestrator overrides. Ensure every effective deployment input is tracked by Watch Paths; verify inheritance in the actual parser.
- Treat generated domains, Shared references and parser-managed variables as runtime state. Verify the resulting application configuration and reconcile stale entries before declaring changes complete.
- Preserve data, privilege boundaries and existing deployments. Distinguish source validation from parser, deployment and real-consumer acceptance; never use a speculative redeploy to settle an unresolved contract.
