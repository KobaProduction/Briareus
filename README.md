# BRI V1

BRI V1 evolves the legacy MCP platform with one public Gateway, a resource-bound
MCP OAuth facade, ZITADEL human identity and independent provider deployments.
The V1 foundation is tracked in #546. Branch `v1` is the active baseline; the
larger V2 architecture remains in branch `v2`. Source changes do not constitute
a live authentication or deployment cutover.

## Architecture

```text
ChatGPT / MCP clients
        |
        | HTTPS
        v
gateway
  |  \
  |   \-- OAuth routes ----------> auth
  |                                 |
  |                                 +-- ZITADEL login / DCR / MCP token state
  |
  +-- /github/mcp   -------------> github
  +-- /gitlab/mcp   -------------> gitlab
  +-- /files/mcp    -------------> files
  +-- /web/mcp      -------------> web (curl + persistent Chromium)
  +-- /analysis/mcp -------------> analysis ---> ghidra (private)
  +-- /terminal/mcp -------------> terminal
  +-- /observability/mcp -------> observability (SigNoz + Coolify, read-only)
  +-- /admin        -------------> Control Panel UI
```

The public domain is `mcp.koba-nexus.ru`. Gateway is the only process assigned that
public domain. Auth and all provider runtimes remain private on the Compose network.

## Public MCP surfaces

```text
/mcp
/github/mcp
/gitlab/mcp
/files/mcp
/web/mcp
/analysis/mcp
/terminal/mcp
/observability/mcp
/admin/*        -> standalone Control Panel UI
/api/*          -> Control Panel API/realtime
```

Native Ghidra is not a public MCP surface. Analysis is the external structured-analysis
contract; Ghidra is an implementation backend.

## OAuth boundary

ZITADEL owns human login. The Control Panel API owns its server-side OIDC state,
callback, session and CSRF protection; the UI redirects to `/api/auth/login` and
never collects a password or receives identity tokens.

The `auth` runtime remains the MCP OAuth facade. Every public MCP URL is an exact
protected resource and access-token audience. Registration, PKCE, refresh/replay
state and signing material retain a single owner. Replacing the upstream GitHub
login must preserve resource binding: direct ZITADEL DCR does not provide the same
contract because its `resource` input is ignored.

The issuer and callback origins are explicit environment contracts. A new local
stand has its own localhost-only identity and fresh state; existing public
origins, credentials and volumes are not silently renamed or reused. The GitHub
MCP provider remains supported independently of removal of GitHub human login.

## Repository layout

```text
src/
├── auth_service/
├── bridge/
├── common/
├── control_panel_api/
└── modules/
    ├── github/
    ├── gitlab/
    ├── files/
    ├── web/
    ├── analysis/
    ├── ghidra/
    └── terminal/
```

## Runtime and deployment isolation

The V1 decomposition assigns independent build/update boundaries to stable
Dependencies, Gateway, Control Panel API, Control Panel UI and each MCP provider.
Persistent Chromium and Ghidra runtimes have their own lifecycles; updating the
Web or Analysis provider must not recreate their stateful dependencies.

Each deployable watches its own source, manifest, Dockerfile and dependency
inputs, plus the focused shared packages it actually consumes. Shared code has
one implementation with explicit consumers; a UI change does not select the
API, providers or dependencies. Generic Compose and saved Coolify parser/network/
Watch Path configuration are verified separately before a real rollout.

Gateway remains available independently of a particular provider and reuses
lazy backend MCP connections. Provider accounts and credentials remain owned by
Control Panel API; Valkey is a private cache, not a second source of truth.
Provider runtimes do not open the Control Panel database directly.

See [the V1 architecture](docs/architecture/overview.md) and system deployment
documentation for source ownership, preserved state and acceptance boundaries.
The historical `deploy/coolify` topology is rollback/provenance material until
its replacement receives explicit runtime/cutover acceptance.

## Locked Python dependencies

Production and CI install dependencies from committed `uv.lock`:

```text
uv sync --frozen --no-dev --no-install-project
```

This prevents clean deployments from resolving a different dependency graph.

Local contributions can enable the tracked source and UI validation hook with
`git config core.hooksPath .githooks`. The tracked hook retains the repository
validation commands. Source-phase work does not authorize running tests or
changing fixtures; after all source owners finish, the owner separately
authorizes the test phase. Hooks and quality thresholds remain enabled.

## Files

Files is the path-based file manager for the shared persistent `/workspace` filesystem.
Terminal, Files, Web/curl and the Control Panel API see the same working files immediately.
There is no separate content-addressed file store and no `file_id` storage contract.

## Analysis

Analysis dynamically adapts the internal analysis backend catalog into the project
terminology and validates/normalizes arguments before dispatch. Internal backend naming
is not part of the external ChatGPT contract.

## Control Panel API

Control Panel API owns provider accounts, encrypted credentials, invocation telemetry, settings,
Files administration and the Control Panel API/realtime backend. GitHub, GitLab, SigNoz and Coolify can each have
multiple named accounts. SigNoz API keys and Coolify API tokens are encrypted in Control Panel API;
they are not deployment environment variables. Provider runtimes resolve the explicitly
selected `account_id`/alias through the private Control Panel API rather than opening the
Control Panel database directly. Expensive
workspace statistics and Reverse overview/coverage calculations are refreshed by background
workers into persistent snapshots; the standalone frontend consumes the latest cached value with freshness
metadata instead of performing long scans or analyses in the HTTP request path.

## License

MIT


## Terminal

Terminal is a dedicated non-root Linux development runtime exposed at `/terminal/mcp`.
It provides persistent workspaces, bounded shell execution, durable long-running jobs,
interactive PTY input/output and cursor-based incremental logs. Terminal, Files, Curl and
Control Panel API file operations share the same mutable `/workspace` volume, so working files are
immediately available by path without import/export copies. System toolchain packages are
installed in the image; normal runtime commands execute as the unprivileged service user.
Terminal command/stdin/output payloads are bounded or omitted in Control Panel API MCP-call history.

## Web browser

For external operator Chrome session status and recovery, see\n[External Playwright MCP sessions](docs/external-browser-sessions.md).\n\nThe Web MCP combines structured curl operations with a persistent Playwright/Chromium
browser profile. Browser cookies and local session state live in a dedicated persistent
volume, while screenshots, uploads and downloads use the shared `/workspace`. Browser
snapshots return bounded page text plus short-lived interactive element refs so agents can
click and fill without serializing full page HTML into model context. Browser page content
and filled values are omitted from Control Panel API audit payloads; tool/status metadata remains
observable.

The standalone Control Panel UI uses the session-authenticated
`/api/browser/operator/ws` public Gateway surface for the same persistent Chromium profile. It shares
tabs, input, agent/developer access controls, DevTools, reopen/cleanup operations and browser
state with the Web runtime. Viewport changes use public `PUT /api/browser/viewport`. The legacy
HTML Browser Operator and ticket-authenticated `/admin/browser/ws` surface have been removed.


The Web surface also mounts Google's official `chrome-devtools-mcp` server (pinned to
`1.10.1`) under the `devtools_` namespace instead of reimplementing Chrome debugging RPCs.
It connects only to the same loopback CDP endpoint used by the persistent browser. Agent
Developer access is a separate browser-wide privilege and defaults to off; privileged calls
require both `Agents: On` and `Developer: On`. Turning either switch off disconnects the
privileged stdio upstream. Full Developer mode intentionally sees all browser targets rather
than honoring per-tab basic-browser locks. The operator UI persists the Developer switch in the
browser policy; a fresh profile starts with Developer access off.

The upstream exposes its native console, network, JavaScript evaluation, DOM/CSS, performance,
memory and extension tools without Koba schema translation. Extension/source filesystem access
is restricted to `/workspace`; file navigations and CrUX URL uploads are disabled. DevTools MCP
arguments and results are omitted from Control Panel API audit payloads because they may contain
cookies, authorization headers, JavaScript, request bodies or authenticated page data. Tool
name, status, duration and traces remain observable. The runtime uses normal Chromium
capabilities; it does not add fingerprint spoofing or site-control bypass logic.

## OAuth sessions

The authorization runtime reports safe OAuth session metadata to Control Panel API without
copying access or refresh tokens. Control Panel API shows client/resource identity, last use,
refresh activity, token expiry, revocation and the latest authentication error. Refresh
rotation keeps a bounded two-minute idempotency window in the encrypted persistent OAuth
store. Concurrent requests and retries that cross an auth-container restart reuse the same
rotated result instead of spending the one-time upstream refresh token again. Client-facing
FastMCP access tokens use a 30-day lifetime; every request still validates the configured upstream identity
session, so upstream expiry/revocation is not extended, while unnecessary daily client refresh
rotation is avoided. Refresh attempts emit token-safe correlation logs for request, replay,
upstream exchange, race recovery and terminal `reauth_required` branches; raw tokens are never
logged. An upstream refresh token that was already invalid before these protections cannot be
reconstructed and requires one fresh user authorization.

## Observability

Observability is one unified read-only MCP surface at `/observability/mcp`. Control Panel API keeps
SigNoz and Coolify connections as separate account types because their credentials and APIs are
different, but ChatGPT connects to only this one surface. `observability_sources` lists both
provider types and their aliases; data tools require an explicit account selector.

SigNoz-backed tools provide runtime logs, traces, metrics/query access, service discovery and
field discovery. Coolify-backed tools provide application and deployment state. Coolify runtime
logs, environment variables, secrets and all deploy/restart/mutation operations are deliberately
absent; runtime diagnostics belong to the SigNoz side of the same Observability interface.

Hot-path telemetry distinguishes cache/Control Panel API access, backend MCP session reuse, provider
HTTP latency and connection-pool wait, and Control Panel API repository operations. Control Panel API audit
delivery is batched through a bounded in-memory queue: each MCP call remains an individual audit
record and metric event, while short batches share one internal HTTP request and one SQL
transaction. Sensitive arguments, credentials, authorization headers, full request URLs and
cache keys are not exported as span attributes.
