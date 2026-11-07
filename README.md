# Briareus V1

Briareus V1 evolves the legacy MCP platform with one public Gateway, external
OpenID Connect authorization and independent provider deployments.
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
  |   \-- /api ------------------> Control Panel API
  |                                 |
  |                                 +-- PostgreSQL application state
  |
  +-- /github/mcp   -------------> github
  +-- /gitlab/mcp   -------------> gitlab
  +-- /server/mcp   -------------> server (files, commands and jobs)
  +-- /web/mcp      -------------> web (persistent browser)
  +-- /analysis/mcp -------------> analysis ---> ghidra adapter ---> external Ghidra MCP
  +-- /observability/mcp -------> observability (SigNoz + Coolify, read-only)
  +-- /admin        -------------> Control Panel UI
```

The operator assigns the public domain to Gateway in Coolify. Gateway is the only
public receiver. The API and provider runtimes share the environment network. The OpenID provider is external.
Browser and MCP clients obtain tokens directly from the configured OpenID provider.

## Public MCP surfaces

```text
/mcp
/github/mcp
/gitlab/mcp
/server/mcp
/web/mcp
/analysis/mcp
/observability/mcp
/admin/*        -> standalone Control Panel UI
/api/*          -> Control Panel API/realtime
```

Ghidra MCP is not a public MCP surface. Analysis is the external structured-analysis
contract; Ghidra is an implementation backend.

## Authorization boundary

An external OpenID Connect provider owns login, SSO cookies, code exchange,
access/refresh tokens and logout. The UI uses `oidc-client-ts` with Authorization
Code + PKCE, discovery and memory-only tokens. Transaction state stays in
sessionStorage. Briareus does not issue tokens or maintain login sessions.

API and Gateway discover `jwks_uri` from the configured issuer, cache metadata and
JWKS for five minutes, and verify signatures, issuer, API audience and expiry.
A configured claim path maps provider roles to the required application role
(default `access`); one assignment grants full panel and MCP access.
Both flat/nested role lists (including Keycloak client roles) and organization-bound
grants (including ZITADEL project roles) are supported without vendor endpoints.
See [OIDC provider configuration](docs/oidc.md).

HTTP uses Bearer authorization. Browser WebSockets send the token in an offered
subprotocol alongside `briareus.v1`; only the latter is negotiated. Credentials
never go in URL query strings. Browser-origin checks remain for mutations/sockets.
Expired sockets close; invalid JWTs fail closed. Revocation/removal of a project
assignment takes effect for existing JWTs at expiry, so choose short access-token
lifetimes in the provider. JWKS sets are cached for five minutes and refresh on unknown
key IDs; there is no provider request on every tool invocation.

MCP clients use pre-registered clients in the external authorization server.
Protected-resource metadata advertises the configured issuer and scopes. The API
and MCP surfaces share the configured API audience; endpoint URLs do not imply
per-tool audience isolation. Briareus does not enable anonymous server-wide DCR.
See [MCP authorization setup](docs/oauth-chatgpt.md).

## Repository layout

```text
services/
в”њв”Ђв”Ђ control-panel/
в”‚   в”њв”Ђв”Ђ ui/                     # frontend and frozen Bun build
в”‚   в””в”Ђв”Ђ api/                    # API, hosted OAuth, migrations and tests
в”њв”Ђв”Ђ gateway/                    # public routing
в”њв”Ђв”Ђ dependencies/               # Postgres, Valkey, Chromium
в”‚   в””в”Ђв”Ђ chromium/
в””в”Ђв”Ђ hands/
    в”њв”Ђв”Ђ server/    в”њв”Ђв”Ђ github/    в”њв”Ђв”Ђ gitlab/    в”њв”Ђв”Ђ web/
    в””в”Ђв”Ђ analysis/  в”њв”Ђв”Ђ ghidra/    в””в”Ђв”Ђ observability/
shared/
в”њв”Ђв”Ђ contracts/{json-values,accounts,invocation-events,oauth-sessions,
в”‚              http-surface,mcp-resources,tool-annotations}/
в”њв”Ђв”Ђ policies/{browser,github,gitlab,terminal,mcp}/
в”њв”Ђв”Ђ control-panel/{browser,github,gitlab,terminal,mcp}-policy-client/
в”њв”Ђв”Ђ control-panel/oauth-sessions-client/
в”њв”Ђв”Ђ python/{environment-models,environment-parsing,secret-files}/
в”њв”Ђв”Ђ server/workspace-mount/     # one mount and safe project paths
в”њв”Ђв”Ђ browser/debug-tickets/     # signed target/session-bound debug tickets
в”њв”Ђв”Ђ http_transport/  в”њв”Ђв”Ђ websocket_transport/  в”њв”Ђв”Ђ mcp_client/
в””в”Ђв”Ђ cache/  в”њв”Ђв”Ђ git/  в”њв”Ђв”Ђ workspace/  в”њв”Ђв”Ђ telemetry/  в”њв”Ђв”Ђ hand_runtime/  в””в”Ђв”Ђ service_runtime/
tests/
в”њв”Ђв”Ђ support/                    # reusable fixtures
в””в”Ђв”Ђ integration/                # cross-service acceptance contracts
```

Each Python owner has its own `src/<package>`, `pyproject.toml`, frozen `uv.lock`,
Dockerfile, Dockerfile-specific context filter and Compose entrypoints. Focused
tests live with their service. Shared capabilities have one implementation;
settings belong to their capability or service, with no omnibus common package.


## Runtime and deployment isolation

The V1 decomposition assigns independent build/update boundaries to stable
Dependencies, Gateway, Control Panel API, Control Panel UI and each MCP provider.
PostgreSQL, Valkey and standalone Chromium share one Dependencies deployment.
Ghidra MCP uses its existing external deployment through required operator URLs.
Dependency images contain no Briareus
application source or shared modules and watch only their own infrastructure directory. Updating the API, UI, Web or Analysis provider
does not redeploy that dependency resource. All internal containers use one common
environment network; production ZITADEL and Ghidra MCP stay outside it. The panel uses PostgreSQL,
with SQLAlchemy, psycopg and versioned Alembic migrations. See
[deployment](deploy/README.md) for schema upgrades and local-only fixtures.

Each deployable watches its own source, manifest, Dockerfile and dependency
inputs, plus the focused shared packages it actually consumes. Shared code has
one implementation with explicit consumers; a UI change does not select the
API, providers or dependencies. Generic Compose and saved Coolify parser/network/
Watch Path configuration are verified separately before a real rollout.

Gateway remains available independently of a particular provider and reuses
lazy backend MCP connections. Provider accounts and credentials remain owned by
Control Panel API; Valkey is a private cache, not a second source of truth.
Provider runtimes do not open the Control Panel PostgreSQL database directly.

See [the V1 architecture](docs/architecture/overview.md) and system deployment
documentation for source ownership, preserved state and acceptance boundaries.
The historical `deploy/coolify` topology is rollback/provenance material until
its replacement receives explicit runtime/cutover acceptance.

## Locked Python dependencies

Production images install their service-owned frozen lock. The root `uv.lock`
is the aggregate development and test environment:

```text
uv sync --frozen --no-dev --no-install-project
```

This prevents clean deployments from resolving a different dependency graph.

Enable the tracked pre-commit and pre-push hooks with
`git config core.hooksPath .githooks`. Python functions are limited to 50
statements, 15 branches, cyclomatic complexity 15 and cognitive complexity 15
(30 for tests). Strict Mypy rejects explicit `Any`, unparameterized generics,
untyped definitions and unresolved imports. Validated JSON values remain the
boundary format for external HTTP/MCP payloads; internal operation state uses
named models and typed protocols.

During development, run checks for the changed owners. At the final boundary,
stage the complete changes and run
`uv run --frozen --no-env-file --group quality python scripts/quality_gate.py --all --tests`.
This also checks packaging, Compose, real PostgreSQL migrations and the UI build.
Hooks require the tested source to match the index/outgoing commit and reuse the
successful result only while file contents and index metadata stay identical.
CI independently runs the selected static and contract checks.

## Files

Files is the path-based file manager for the shared persistent `/workspace` filesystem.
Server terminal, Files, Web downloads and the Control Panel API share these files.
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


## Server

Server is one non-root runtime exposed at `/server/mcp`, combining file operations
and terminal commands/jobs. Its source is one `briareus_server` package with files
and terminal capability modules; there are no separate Files or Terminal services.
It provides persistent workspaces, bounded shell execution, durable long-running jobs,
interactive PTY input/output and cursor-based incremental logs. Server commands/files, GitHub/GitLab checkout, browser downloads and
Control Panel API file operations share one mutable mount configured by
`SERVER_MOUNT_PATH` (default `/workspace`), so working files are
immediately available by path without import/export copies. System toolchain packages are
installed in the image; normal runtime commands execute as the unprivileged service user.
Terminal command/stdin/output payloads are bounded or omitted in Control Panel API MCP-call history.

## Web browser

For external operator Chrome session status and recovery, see
[External Playwright MCP sessions](docs/external-browser-sessions.md).

The Web MCP provides browser operations over a persistent external Chromium
profile. HTTP command-line work uses the curl binary installed in Server. Browser cookies and local session state live in a dedicated persistent
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

User authorization and token lifecycle are managed by the external OIDC provider. Briareus records
application invocation audit, not a second OAuth session authority.

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
