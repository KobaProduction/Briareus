# Coolify Variable Materialization

Load when authoring or validating variables parsed from Compose. This module defines parser semantics, **not** a final naming glossary.

## Naming decision

This module owns **parser mechanics**, not the naming glossary. When adding or reviewing operator/Shared/secret keys, load `variable-glossary.md` or `telemetry-variables.md` on demand. Keep official image/SDK ENV names where required and translate approved operator keys at the boundary. Exposed names, Required/default changes and secret scope need explicit approval; report legacy mismatches without automatic rename.

## Configuration classification

Classify every configurable value before writing the manifest.

| Kind | Compose treatment | Coolify treatment |
| --- | --- | --- |
| secret/credential/private key/token | reference only | protected shared-variable scope selected by ownership and access policy |
| mutable external address, bind IP, remote endpoint, externally meaningful listen port | required: `${VAR:?}` | resource variable, intentionally empty until set |
| safe portable default such as timezone or non-sensitive DNS | optional: `${VAR:-default}` | generated resource variable may keep default |
| internal service-to-service host/port | literal service DNS + container port | do not externalize unless a real consumer needs it |
| deployment identity label/metric label | literal if invariant for that stack; variable only when operationally mutable | keep out of shared secret scope |
| managed public HTTP(S) route | Prefer one `SERVICE_URL_*` directive; use `SERVICE_FQDN_*` instead for hostname-only consumers | Coolify-managed route/domain, not a separate Required ENV |
| editable config file | bind mount with inline `content:` | Coolify-managed file mount |

Do not turn every literal into an environment variable. Parameterization is useful only where the value has a real independent lifecycle.

Do not mark a generated `SERVICE_URL_*` as an ordinary Required operator input, or add `SERVICE_FQDN_*` solely for TLS. Public routes need one managed directive under their real receiver; internal-only services do not. Domain and certificate authority remain in Coolify, not in Shared-variable substitution.

## Required variables

For values that must be supplied before deployment:

```yaml
environment:
  PUBLIC_ENDPOINT: ${PUBLIC_ENDPOINT:?}
```

Rules:

- use empty `:?` when the Coolify UI should create a **Required** variable with no default;
- do not use `${VAR:?VAR is required}` for Coolify UI materialization unless the deployed parser version is proven to keep the message only as an error message; some parser/UI flows can persist the text after `?` as the variable value;
- do not give a fallback to a value whose absence should block deployment;
- declare the required variable under the owning service's `environment:` even when Compose also uses it in `ports:`, `command:`, labels or another field. Coolify parser discovery is environment/build-argument oriented; a variable used only elsewhere may fail to appear as a managed Required entry;
- using the same `${VAR:?}` expression again in `ports:` or `command:` is acceptable when Compose interpolation itself must also fail closed.

Bad:

```yaml
ports:
  - '${BIND_IP:-0.0.0.0}:8080:8080'
```

when binding every interface would be unsafe or unintended.

Good:

```yaml
environment:
  BIND_IP: ${BIND_IP:?}
ports:
  - '${BIND_IP:?}:8080:8080'
```

## Optional defaults

Use `${VAR:-default}` only for genuinely safe portable defaults: `TZ`, non-sensitive resolver, or optionally configurable container listener port. Prefer upstream names (`TZ`, `HTTP_PROXY`) over invented service-specific aliases. A shared `TZ` should replace per-app keys unless required by the image.

Select Team/Project/Environment/Resource shared scope according to ownership; Coolify Shared references **do not cascade** or inherit. Project overrides must be explicit. For consumers needing both `TZ` and `tz`, map both from one variable bound to a verified reference such as `{{team.TZ}}`; do not introduce two timezones.

## Coolify variable flags

Use Coolify variable flags intentionally:

- **Runtime** — enable when the running container needs the value;
- **Buildtime** — enable only when image/build interpolation actually needs it; do not expose runtime-only secrets to builds by default;
- **Literal** — use when characters such as the dollar sign must remain unexpanded;
- **Multiline** — use for certificates, keys or configuration blobs that genuinely contain line breaks; treat them as secret when sensitive;
- **Preview** — keep separate values only when preview deployments really need a distinct contract.

Do not accept whatever flags Coolify generated without checking whether they match the consumer.

Managed/generated `SERVICE_*` variables belong to Coolify's parser state. Do not convert them into hand-maintained business configuration.
