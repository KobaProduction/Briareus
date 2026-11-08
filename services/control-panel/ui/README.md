# Control Panel UI

Standalone Vue 3 + TypeScript + Vite + Tailwind CSS Control Panel frontend.

## Isolation boundary

The frontend container is built with `services/control-panel/ui/` as its Docker build context. The build cannot read or copy the Python backend, root `Dockerfile`, `src/`, `uv.lock`, or the backend Compose topology.

For a standalone Coolify application use:

- branch: `v1`;
- base/build directory: `control-panel-ui`;
- Dockerfile: `Dockerfile`;
- container port: `8080`.

No backend container is required to build or start the frontend.

## Runtime modes

### Preview

Set `CONTROL_PANEL_UI_PREVIEW=true` only for an explicit frontend preview. Preview uses local demonstration state and makes no Control Panel API requests. Missing runtime configuration defaults to connected mode and never admits a user from browser storage.

### Connected

Connected mode is the default. `CONTROL_PANEL_UI_PREVIEW=false` is already the default.

The frontend container is a static SPA only. It does not know the Control Panel API origin and does not proxy API traffic. The public MCP gateway owns routing:

- `/admin/*` -> frontend container, stripping the `/admin` prefix before forwarding;
- `/api/*` -> Control Panel API;
- `/api/realtime` -> Control Panel realtime WebSocket;
- `/api/browser/operator/ws` -> Browser Operator WebSocket.

## Architecture boundaries

- `app/` - composition root and global design tokens;
- `pages/` - route-level screens;
- `widgets/` - large reusable regions;
- `features/` - user-facing capabilities;
- `shared/api/` - typed backend transport;
- `shared/ui/` - repository-owned shadcn-style primitives;
- `shared/lib/` - framework-independent helpers and browser-local UI preferences.

Shared application state belongs to Pinia. Persistence is opt-in: UI preferences and provider-issued OIDC user/transaction records use the central localStorage persistence adapter. Operational caches, connection state, notifications and telemetry buffers are not persisted. Browser caches never authorize API operations; the backend verifies the provider token and node role on each request.

## Discovered MCP services

`bootstrap.services` is the authority for the provider catalog. Each entry has
`id`, `name`, `group`, `connected` and its public `mcp_path`; `checked_at` records
when discovery checked the topology. The authenticated UI refreshes the catalog
and hides unavailable providers by default. The reveal switch shows disabled
entries. An unavailable deep link never mounts that provider's controls.
Unknown connected providers get their own MCP connection URL without requiring a
new hardcoded navigation entry.

Provider pages follow the deployment groups under `pages/services/`: `svc`,
`web/playwright`, `observability/signoz`, `infrastructure/coolify`, `server`, and
`analysis`. Internal and external browsers are modes of the same Playwright MCP.
Files and Terminal share Server. Ghidra owns its projects and worker controls;
the Analysis MCP has its own independent connection. Frontend telemetry belongs
to Interface settings and is not an MCP provider.

## Interactive platform contracts

The frontend is organized by domain slices under `src/pages/<domain>/` and reusable feature code under `src/features/`. Cross-cutting browser infrastructure lives under `src/shared/`.

Current frontend infrastructure includes:

- `shared/i18n/` — RU/EN locale catalogs and persisted language preference;
- `shared/notifications/` — application-wide toast/notification bus;
- `shared/telemetry/` — sanitized browser telemetry facade and local diagnostic buffer;
- `shared/events/` — one topic subscription manager with mock, compatibility and future WebSocket transports;
- `shared/settings/` — typed helpers for preserving full backend settings while domain pages edit only owned values;
- `shared/ui/DataTable.vue` — Ant Design Vue dense table wrapper with virtual scrolling and an end-of-scroll signal.

### Frontend telemetry contract

The browser must never receive an OTLP/Bearer secret. When telemetry is enabled it sends sanitized events to the same-origin endpoint configured by `CONTROL_PANEL_UI_TELEMETRY_ENDPOINT` (default `/api/telemetry`) using the existing authenticated browser session.

The Control Panel API authenticates the browser session and forwards accepted telemetry to the infrastructure telemetry endpoint using server-owned authorization. Passwords, cookies, authorization headers, account credentials, request bodies and other sensitive payload fields are filtered by the frontend telemetry facade and must also be rejected/redacted server-side.

Runtime variables:

- `CONTROL_PANEL_UI_TELEMETRY_ENABLED=true`;
- `CONTROL_PANEL_UI_TELEMETRY_ENDPOINT=/api/telemetry`;
- `CONTROL_PANEL_UI_TELEMETRY_SAMPLE_RATE=1`;
- `CONTROL_PANEL_UI_EVENTS_MODE=hybrid` (`mock`, `hybrid`, or `websocket`);
- `CONTROL_PANEL_UI_EVENTS_URL=/api/realtime`.

`hybrid` uses the unified Control Panel WebSocket as the primary transport and retains the existing MCP Calls SSE stream only as a compatibility fallback during migration. Deployment may switch to `websocket` after the fallback is no longer required.

The implementation roadmap and backend follow-ups are tracked in GitHub issue #233.

### Production admin routing

The Control Panel UI is built for the public base `/admin/`. Browser-visible assets and runtime configuration use that prefix, while Control Panel API and WebSocket calls remain root-level `/api/*`.

The public gateway owns the split:

- `/admin/` and `/admin/*` -> frontend container with `/admin` stripped upstream;
- `/api/*` -> Control Panel API;
- MCP surfaces remain independent.

The frontend nginx serves only static SPA files and `/health`; it must not proxy Control Panel API or WebSocket traffic.

## Interaction regression tests

Use `bun install --frozen-lockfile`, then `bun run --bun typecheck` and
`bun run --bun build`. The frontend workflow runs
these checks on changes to this directory.

Component tests mount the real Vue table and account panel. Provider calls are
mocked, so tests never verify, create, or delete production accounts. Happy DOM
has no layout: virtual table tests use deterministic virtual positions to test
both render branches; browser scroll/layout and native keyboard activation still
require browser acceptance. Keep those validation levels separate.

## Identity and preference migration

The panel uses the configured provider through Authorization Code + PKCE. The
OIDC library stores its serialized user and transaction records in Pinia stores
with `pinia-plugin-persistedstate`. Persistence uses localStorage and is shared
between tabs. A reload reuses a still-valid token without another authorization
code exchange. Expired tokens are renewed with the provider refresh token;
rejected renewal clears the stored user. Browser locks coordinate refresh-token
rotation between tabs, and account changes reset visible per-user caches.
No local authorization flag, panel-issued token or SSO logout is introduced.

UI preferences move to `briareus:ui:v1`. On the first read without that key, the UI
copies valid values from `mcp-bridge:ui:v2`, or the older `mcp-management:ui`
schema. The old entries remain available for rollback; credentials and auth hints
are never migrated into authority. Existing API `management` settings fields and
`management.events` topic remain wire identifiers during this source migration,
not component names. Their eventual removal requires a coordinated contract
migration, separately from browser preference migration.

Runtime inputs use `CONTROL_PANEL_UI_*`; the Vite-only local backend input is
`VITE_CONTROL_PANEL_DEV_BACKEND`. Existing deployment operator values must be
mapped deliberately when adopting the new source; no live ENV rename is implied.

The identity transition requires existing local-password panel users to sign in
again through ZITADEL. An old `management_admin` session is not an identity
mapping, even when the display username matches. Backend account/config/audit
rows and encryption/signing keys remain preserved; reauthentication does not
authorize database reset or a live rollout. Telemetry uses the same provider bearer token as other API requests; a Beacon cannot supply its required Authorization header.
