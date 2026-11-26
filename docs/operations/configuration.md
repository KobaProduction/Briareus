# V1 configuration owners and secrets

This is an **ownership map**, not a copy of real Coolify variable values.

| Owner | Key configuration | Rule |
| --- | --- | --- |
| Gateway only | `BRIAREUS_NODE_ID`, public origin, `OIDC_ISSUER_URL`, `OIDC_AUDIENCE`, roles policy | Sole server-side identity authority |
| Gateway | `OIDC_BROWSER_CLIENT_ID` | Existing public browser registration, Code + PKCE, no client secret |
| Gateway | `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` when introspection is selected | Independent confidential registration; protected secret |
| Gateway only | `OIDC_PROVISIONING_TOKEN` | Separate protected ZITADEL role-provisioning credential |
| Internal services | `BRIAREUS_SERVICE_TOKEN` | Separate shared private credential; recreate consumers after rotation |
| Dependencies + API | PostgreSQL connection settings and protected password | Production database; do not silently switch or reset |
| Dependencies + consumers | Valkey ACL credentials and private URLs | Cache/discovery, not user authority |
| Dependencies | `CHROMIUM_MEMORY_LIMIT`, `CHROMIUM_SHM_SIZE` (default `4g`) and configured swap policy | Container cgroup memory limit and shared-memory tmpfs capacity; live changes require separate verification |
| Serena | `SERENA_MAX_PROCESSES` (default `0` = unlimited), `SERENA_MEMORY_LIMIT`, idle cleanup | Optional project-session cap and container memory budget |
| Playwright | `BROWSER_CLICK_TIMEOUT_MS`, CDP connect/reconnect and idle cleanup settings | Runtime behavior, not Chromium cgroup |
| Hands | Provider account selectors, scoped policies and upstream URLs | Provider credentials are stored encrypted in Control Panel API |

For a shared external OIDC provider, put the **non-secret** `OIDC_ISSUER_URL` in
Team Shared Variables and supply it to each explicitly authorized consuming
Gateway resource through its own `${OIDC_ISSUER_URL:?}` application variable
(reference `{{team.OIDC_ISSUER_URL}}`). Other project/organization/node-scoped
OIDC settings, including audience and role mappings, stay resource-specific.
Do not place ZITADEL admin credentials or resource-server introspection
credentials at Team scope solely because the issuer URL is shared. Team Shared
values are not inherited automatically; check each reference at cutover.

API receives node identity and origin through the authenticated private Gateway contract, not environment variables. Browser and resource registrations remain distinct inside Gateway. See [OIDC migration](../oidc.md#client-naming-and-migration).

Configured public addresses, node names and non-secret deployment labels belong to application runtime variables. Secret **values** must be protected; no raw tokens/keys in Git, docs, logs, pasted commands, or build artifacts. OIDC external HTTPS, audience and project-role semantics: [OIDC](../oidc.md), [MCP OAuth](../oauth-chatgpt.md).

`DEPLOYMENT_ENVIRONMENT` determines deployment labels and network/volume namespaces. Valid V1 deployment values include `development`, `staging`, `production` and `test`. Multiple nodes must not share the same physical persistent volumes solely because their environment names match.

### Coolify provider account permissions

Coolify API token abilities are not interchangeable: `read` lists safe metadata,
`read:sensitive` permits runtime logs and nonlocked application-local values,
and `deploy` permits queued restart/deploy actions. A Coolify 403 response now identifies the required API permission and possible owner/scope restrictions without exposing the token. Shared Variables are
**never** returned raw; even an administrator sees only status/length or a
bounded 2+2 mask through this Hand. Reading an application-local value
requires a separately confirmed, scoped one-time MCP challenge and explicit
operator permission. Locked/Shared values remain blocked. See the
[Coolify Hand security contract](../../services/hands/infrastructure/coolify/README.md).

A Coolify 403 may indicate missing abilities, insufficient team role, selected
resource scope, or an API IP allowlist. Do not work around it with another
account or a root token without explicit operator authorization.

For exact service environment requirements and defaults, inspect the owner `settings.py`, `docker-compose.yaml`, generated Coolify Compose and saved Coolify resource configuration. These layers can differ; do not infer live state from this document.
