# V1 configuration owners and secrets

This is an **ownership map**, not a copy of real Coolify variable values.

| Owner | Key configuration | Rule |
| --- | --- | --- |
| Node API + Gateway | `BRIAREUS_NODE_ID`, `OIDC_ISSUER_URL`, `OIDC_AUDIENCE`, roles policy | Same node identity and verification policy |
| Control Panel UI / API | `OIDC_PANEL_CLIENT_ID`, public origins, allowed callbacks | External Code + PKCE; no local credential issuer |
| API only | `OIDC_PROVISIONING_PROVIDER`, `OIDC_PROVISIONING_TOKEN` | Only API may receive private ZITADEL provisioning token |
| Internal services | `BRIAREUS_SERVICE_TOKEN` | Separate shared private credential; recreate consumers after rotation |
| Dependencies + API | PostgreSQL connection settings and protected password | Production database; do not silently switch or reset |
| Dependencies + consumers | Valkey ACL credentials and private URLs | Cache/discovery, not user authority |
| Dependencies | `CHROMIUM_MEMORY_LIMIT` and configured swap policy | Container cgroup memory limit; live changes require separate verification |
| Playwright | `BROWSER_CLICK_TIMEOUT_MS`, CDP connect/reconnect and idle cleanup settings | Runtime behavior, not Chromium cgroup |
| Hands | Provider account selectors, scoped policies and upstream URLs | Provider credentials are stored encrypted in Control Panel API |

Configured public addresses, node names and non-secret deployment labels belong to application runtime variables. Secret **values** must be protected; no raw tokens/keys in Git, docs, logs, pasted commands, or build artifacts. OIDC external HTTPS, audience and project-role semantics: [OIDC](../oidc.md), [MCP OAuth](../oauth-chatgpt.md).

`DEPLOYMENT_ENVIRONMENT` determines deployment labels and network/volume namespaces. Valid V1 deployment values include `development`, `staging`, `production` and `test`. Multiple nodes must not share the same physical persistent volumes solely because their environment names match.

For exact service environment requirements and defaults, inspect the owner `settings.py`, `docker-compose.yaml`, generated Coolify Compose and saved Coolify resource configuration. These layers can differ; do not infer live state from this document.
