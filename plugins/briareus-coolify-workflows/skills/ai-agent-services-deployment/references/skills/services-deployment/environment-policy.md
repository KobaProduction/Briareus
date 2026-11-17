# Deployment Environment Policy

Load when deciding whether a setting belongs in ENV, Compose, shared configuration, a secret provider or application-owned state. Names and templates are subject to explicit operator approval; the canonical cross-service variable glossary is pending agreement.

## ENV design gate — expose only genuine operator configuration

**Before** adding an ENV key, `.env.example`, Shared Variable or Compose `environment:`, decide whether it is genuinely operated or derivable. ENV is an **external contract**, not a repository of constants.

For every key identify:
1. **Operator:** who legitimately sets/changes it? If nobody, use code/Git.
2. **Owner:** which exact subsystem/resource consumes it? Do not blend DB, authentication, invitations, idempotency and storage into one generic prefix.
3. **Independence:** can the consumer derive it from topology or existing inputs? Avoid redundant DB URL plus components, or internal/public addresses without separate consumers.
4. **Placement:** invariants in code, stable DNS/ports/topology in Compose, operator inputs in Coolify, secret values in protected storage. ENV delivers values, not necessarily owns them.
5. **Default:** unpredictable external origins/secrets are blank Required and fail closed; safe canonical defaults stay in code/Compose. Do not expose internal tuning without operator use.

### Naming

For new or questionable operator keys load `variable-glossary.md` (OpenTelemetry → `telemetry-variables.md`). Do **not** load the glossary when deploying an already approved, unchanged configuration. Keep upstream image/SDK variables untouched; map approved short operator names to them only at a real boundary. Within one resource use concise keys; qualify the actual owner in multi-consumer and Shared/secret namespaces. Full words such as `USERNAME`, `PASSWORD`, `DATABASE` are preferred for our keys. Prefer environment Shared scopes to environment suffixes. New aliases and live renames require explicit approval.

### Required, default and internal
- **Required operator input:** blank Required Coolify variable or protected secret (using its approved scoped key).
- **Safe optional override:** owning service's portable default (for example `POSTGRES_PORT=5432`, `TZ=UTC`).
- **Derived architecture/product state:** internal service DNS, normal timeout, first-admin onboarding state belong in code/topology, not ENV.

A deployment-specific `.env.example` lists minimal approved operator inputs. Do not combine incompatible old/new databases, origins and secrets. Optional keys with defaults are not Required.

### Feature/security switches
Never expose a toggle to bypass core behavior or mandatory auth/service identity. Deploy secure runtime or do not deploy. Absent trust material fails closed. Infer first-admin setup from durable state, not `ENABLE_PREVIEW` or `PRINT_BOOTSTRAP_SECRET`. Show initial codes only via approved restricted channel until setup, not recoverable general logs. Genuine independent supported features may have explicitly owned switches.

### Secret visibility
- Secret **values** live in protected Shared/secret-provider scope, not in Git/images/samples/pasted ENV. Preserve Project secret access boundaries against agents editing Application ENV; do not relocate secrets into agent-readable scope.
- Resource ENV can carry references but resolved process ENV may be plaintext. Do not grant agents process/shell-env, raw logs, reveal controls or value APIs because they can edit ENV. Verify RBAC, not UI masks.
- Select Team/Project/Environment/Server shared scope by consumer and visibility, without implicit inheritance or duplicate values. Rotating, renaming or removing cryptographic material is a migration preserving encrypted data, token verification and replay guarantees; do not substitute plaintext storage.

### Acceptance gate
Review every variable's operator, consuming owner, purpose, scope, origin (operator/derived/secret), Required/default and legacy removal plan. Reject unused/duplicate/unsafe toggles, redundant aliases and unnecessary secrets. Verify the **actual Coolify parser** produces blank Required inputs, approved defaults and resolved Shared references without disclosing values or granting agent access. YAML parsing is not proof.
