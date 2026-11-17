# Control Panel — UI and API

**Owners:** `services/control-panel/ui` and `services/control-panel/api`. These are independent applications, not one Management runtime.

## UI

The static Vue SPA is served at `/admin/*` through Gateway. It uses Authorization Code + PKCE with the external OIDC provider. Provider-issued identity and transaction state may persist in Pinia/localStorage, but browser storage never grants API permissions. UI preferences and telemetry have separate non-authoritative storage rules.

## API

Gateway forwards `/api/*` to Control Panel API and routes realtime and Browser Operator WebSockets. API validates the external access token and required node role, manages selected GitHub/GitLab/SigNoz/Coolify accounts and encrypted credentials, records bounded invocation audit, and owns application data.

The API **defaults to PostgreSQL**, with SQLAlchemy and versioned Alembic migration. SQLite can be **explicitly selected for local/test** with its own migration path; it is not a silent fallback in production. Failed migrations must not silently drop or reset application tables. See [database and tests](https://github.com/KobaProduction/Briareus/blob/v1/services/control-panel/api/tests/README.md).

API/Gateway read the shared `BRIAREUS_SERVICE_TOKEN` for private service communication. The API alone may own the separate ZITADEL role-provisioning credential. A Hand obtains explicitly selected provider access through the private Control Panel client; it does not read the panel database.

## Active contracts

[UI README](../../services/control-panel/ui/README.md) · [API README](../../services/control-panel/api/README.md) · [OIDC](../oidc.md) · [MCP OAuth](../oauth-chatgpt.md) · [deployment](../operations/deployment.md).

Old `management.*` event names or migration preference keys may survive as **wire/storage compatibility**, not as a separate Management service.
