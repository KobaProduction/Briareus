# Briareus V1 Coolify MCP — read, operate and protect secrets

Coolify is an independently deployed **Infrastructure Hand** at
`/infrastructure/coolify/mcp`. Its selected account and encrypted API credential
belong to Control Panel API; the Hand does not open the Control Panel database.

## Permission and application scope

The selected Coolify API token must authorize the **specific application/service**
being accessed. Briareus never elevates Coolify permissions or bypasses its
project/team/IP allowlists. Coolify token abilities:

| Operations | Coolify token permission | Briareus guard |
| --- | --- | --- |
| Metadata, deployment status, variable keys | `read` | Safe response projection |
| Runtime container logs; deploy journal; app variable values | `read:sensitive` | Redaction for logs; two-step app-variable read |
| Restart applications/services and deploy one app | `deploy` | Explicit `confirm=true`; single UUID |
| Shared variable status and masked preview | `read:sensitive` when lengths are available | **Never** return plaintext, any scope |

Coolify may require the token's owner to be a team administrator/owner for
sensitive environment values. **Locked** (`is_shown_once` / `is_locked`) values
are not revealed, even if the token has broad permissions. A restricted
project/resource token may receive 403 for `/team/envs` or `/servers/{uuid}/envs`.
No automatic retry with elevated privileges or account switching is allowed.

If Coolify returns HTTP 403, each MCP call now reports its **required**
API permission (`read`, `read:sensitive` or `deploy`) and directs the agent
to check **Keys & Tokens → API Tokens → Edit → Permissions and Access**.
That error does **not** establish the exact reason by itself: the token
owner's team role, selected resource scope and API IP allowlist can also
deny access. A 401 identifies an invalid/expired token, not a missing
resource grant. `coolify_connection` describes permissions required by
each operation but does not pretend to inspect the live token's grants.

The `write` permission is **not** required for the current Coolify MCP:
it allows creating/updating resource configuration and may permit dangerous
Compose changes. `delete` and `root` are not required for runtime log
inspection or deploy/restart operations.
A successful API response does not imply the caller is permitted to disclose
its contents in chat or another tool.

## Runtime logs versus deployment journal

- `coolify_list_services(account_id)` and
  `coolify_get_service(account_id, service_uuid)` list only safe identities,
  component names and status; never Docker Compose bodies or variables.
- `coolify_get_service_logs(account_id, service_uuid, sub_service_name,
  lines=200, show_timestamps=true, offset=null, max_chars=20000)` reads
  the runtime logs of one **Coolify Service sub-component** from
  `GET /api/v1/services/{uuid}/logs`. Use the component's exact `name`
  returned by `coolify_get_service`, not an arbitrary container ID.
- `coolify_get_application_logs(account_id, application_uuid, lines=200,
  service_name="", show_timestamps=true, offset=null, max_chars=20000)`
  reads container **runtime logs** through
  `GET /api/v1/applications/{uuid}/logs`.
- `service_name` selects a specific Compose container when needed; empty
  selects the application's default logs. Use a bounded 1–5000 line request.
- `coolify_get_deployment_logs(account_id, uuid, ...)` reads the **build/deploy
  journal** from `GET /api/v1/deployments/{uuid}`, not running application logs.

Both tools return bounded, best-effort-redacted text, never HTTP authorization
headers, raw configuration snapshots or command bodies; their results are
omitted from Control Panel's invocation audit. Arbitrary application output
can still contain sensitive information that pattern-based redaction does
not recognize. A missing/403 log response does not mean the container did
not produce logs: Coolify commonly requires `read:sensitive`.

## Shared Variables — status-only or masked

`coolify_shared_variables(account_id, scope, project_uuid="", environment_uuid="",
server_uuid="", mode="status")` supports exactly one explicit scope:
`team`, `project`, `environment` or `server`. It never returns a full value.

- `mode=status`: variable name, presence/configured status, length, metadata.
- `mode=masked`: additionally a mask with **at most first 2 and last 2
  characters**, only when the true length is at least 8. Shorter strings
  are entirely masked, including their initial/final characters.
- Values hidden/locked/redacted by Coolify report `configured=null`,
  `value_length=null` and no preview; do not guess a length or resolve
  a shared reference through another API.
- No `reveal` or unmasked mode is implemented, even for administrators.

`coolify_application_variables` lists safe application metadata, presence and
length but returns **no raw values**. A variable that is Shared or resolves a
`{{team.*}}`, `{{project.*}}`, `{{environment.*}}`, or `{{server.*}}`
reference can never be read through the application-level value tool.

## Application variable reading — two independent calls

1. Verify independent operator permission for this **specific application's
   sensitive variable**. Call
   `coolify_prepare_application_variable_read(account_id, application_uuid, key)`
   for a one-use, short-lived confirmation token. This stage **does not
   disclose the value**.
2. Separately call
   `coolify_confirm_application_variable_read(account_id, application_uuid, key,
   confirmation_token, permission_confirmed=true, purpose="...")`.
   A nonempty, specific purpose is required. Token lifetime: 120 seconds;
   it is consumed on the first authorized attempt, bound to exact account,
   application and variable, and never stored with the value.

Permission assertion in the second tool is **not** a substitute for the
operator's approval or Coolify's actual `read:sensitive` authorization.
The confirm response can contain plaintext for **only a nonshared, unlocked
application-local variable**. Its content and the challenge token are omitted
from Control Panel tool-call audit. Do not echo secrets in chat unless the
authorized operator specifically requests them. A Hand process restart
invalidates unconsumed challenges.

## Lifecycle operations

- `coolify_restart_application(account_id, application_uuid, confirm=true)`
  requests restart through `POST /applications/{uuid}/restart`.
- `coolify_restart_service(account_id, service_uuid, confirm=true,
  pull_latest=false)` requests restart of a Coolify Service resource through
  `POST /services/{uuid}/restart`.
- `coolify_deploy_application(account_id, application_uuid, confirm=true,
  force_rebuild=false)` submits `POST /deploy?uuid={uuid}`.
- `coolify_deploy_service(account_id, service_uuid, confirm=true,
  force_rebuild=false)` submits a deploy of that **one** Service UUID.

These operations require the Coolify `deploy` permission. The Hand never
tries to restart a **physical server**, manipulate its Docker daemon,
restart every application or stop unrelated tenants. A successful POST means
the operation was **submitted**, not that containers were rebuilt/healthy.
Check the returned deployment UUID and authenticated consumer behavior.
Non-idempotent POST requests have **no automatic transport replay**.
Do not invoke these tools without operator authorization for the exact
resource and impact.

## Source, scope and validation

This owner uses its own `pyproject.toml`, frozen lock, Dockerfile,
`docker-compose.yaml` and generated `docker-compose.coolify.yaml`.
No central Management process exists; some legacy wire/audit identifiers
retain that word for compatibility only.

Tests: `services/hands/infrastructure/coolify/tests/`. Deployment and source
checks do not prove the selected live token has `read:sensitive`, `deploy`,
or access to the exact resource. Verify roles using the Coolify API/token
owner, **without inspecting real secret values**. Source:
https://coolify.io/docs/api/permissions .

The count of pending one-use challenges is bounded by
`COOLIFY_READ_CONFIRM_MAX_PENDING` (default 256, range 1–1024). These values
affect only the current Coolify Hand process and never authorize a caller.
