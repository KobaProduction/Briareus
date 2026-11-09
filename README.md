# Briareus V1

Brand SVGs, color variants and service-icon composition are documented in
[assets/brand](assets/brand/README.md).

For MCP connection names, English descriptions, upload icons and the Serena setup,
see the [connection guide](docs/mcp-connections.md).

Briareus V1 evolves the legacy MCP platform with one public Gateway, external
OpenID Connect authorization and independent provider deployments.
The V1 foundation is tracked in #546. Branch `v1` is the active baseline; the
larger V2 architecture remains in branch `v2`. Source changes do not constitute
a live authentication or deployment cutover.

## Architecture

```text
ChatGPT / MCP clients -- HTTPS/Bearer --> Gateway
  /admin/*                   -> Control Panel UI
  /api/*                     -> Control Panel API -> PostgreSQL
  /svc/github/mcp            -> GitHub
  /svc/gitlab/mcp            -> GitLab
  /web/playwright/mcp        -> Playwright (internal/external modes)
  /server/mcp                -> Server (files, commands and jobs)
  /analysis/mcp              -> Analyzer-R
  /analysis/ghidra/mcp       -> Ghidra adapter -> existing external Ghidra MCP
  /observability/signoz/mcp  -> SigNoz
  /infrastructure/coolify/mcp -> Coolify
```

The operator assigns the public domain to Gateway in Coolify. Gateway is the only
public receiver. The API and provider runtimes share the environment network. The OpenID provider is external.
Browser and MCP clients obtain tokens directly from the configured OpenID provider.

## Public MCP surfaces

```text
/svc/github/mcp
/svc/gitlab/mcp
/web/playwright/mcp
/server/mcp
/analysis/mcp
/analysis/ghidra/mcp
/observability/signoz/mcp
/infrastructure/coolify/mcp
/admin/*        -> standalone Control Panel UI
/api/*          -> Control Panel API/realtime
```

Each provider has its own MCP connection. There is no root `/mcp` bridge or
aggregate Web/Observability MCP. The Ghidra route exposes the Briareus adapter;
the existing external Ghidra MCP deployment remains unchanged.

## Authorization boundary

An external OpenID Connect provider owns login, SSO cookies and token issuance.
The UI uses `oidc-client-ts` with Authorization Code + PKCE. Pinia and
`pinia-plugin-persistedstate` persist provider-issued user/transaction records in
localStorage. A valid saved token survives reloads, tabs and browser restarts;
expired tokens use the provider refresh flow, coordinated between tabs. Rejected
renewal clears the stored user. Briareus does not issue its own login tokens or
maintain a second server-side identity session authority.

API and Gateway discover `jwks_uri` from the configured issuer, cache metadata and
JWKS for five minutes, and verify signatures, issuer, API audience and expiry.
A configured claim path maps provider roles to the required node role named by
`BRIAREUS_NODE_ID`; there is no default global `access` role. Its assignment grants
panel and MCP access on that node, independently of deployment availability.
Both flat/nested role lists and organization-bound
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
  control-panel/{ui,api}/
  gateway/
  dependencies/               # PostgreSQL, Valkey, Chromium
  hands/
    svc/{github,gitlab}/
    web/playwright/           # internal and external Playwright modes
    observability/signoz/
    infrastructure/coolify/
    server/                   # files and terminal remain together
    analysis/
    ghidra/                   # adapter to existing external Ghidra MCP
shared/
  services/{catalog,discovery}/
  contracts/  policies/  control-panel/
  python/{environment-models,environment-parsing,secret-files}/
  server/workspace-mount/
  cache/  git/  workspace/  telemetry/  hand_runtime/  service_runtime/
  http_transport/  websocket_transport/  mcp_client/
deploy/
  services.json
  templates/mcp-service.yaml
tests/
  support/
  integration/
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
application source or shared modules and watch only their own infrastructure directory. Updating the API, UI, Playwright or Analysis provider
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

The catalog has four core resources (UI, API, Gateway, Dependencies) and eight
optional MCP hands. Dependencies contains three containers; deploying every hand
would produce twelve resources and fourteen product containers. A node can run a
smaller subset without configuring or starting the absent providers.

Discovery is a shared library inside API/Gateway, not another service. MCP
runtimes announce node-scoped leases in the existing Valkey and expose private
health metadata. API/Gateway verify that metadata over the private network. The
panel shows connected services by default and can reveal unavailable candidates.
Discovery controls availability, not user authorization.


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
Server terminal, Files, Playwright downloads and the Control Panel API share these files.
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

## Playwright browser

Playwright has one MCP at `/web/playwright/mcp`, with internal and external modes.
Internal mode controls the standalone Chromium dependency and its persistent
profile. External mode connects the operator-approved upstream Playwright MCP;
it is not a second Briareus service. There is no Google Chrome DevTools MCP service.
HTTP command-line work uses the curl binary installed in Server, with no curl MCP.

Browser profile state has its own volume. Screenshots, uploads and downloads use
the shared workspace. Browser snapshots return bounded page text and short-lived
interactive element refs. Sensitive page content, filled values and browser
payloads are omitted from invocation audit; tool/status metadata remains visible.

The Control Panel Browser Operator uses `/api/browser/operator/ws` for the managed
Chromium profile through API/Gateway and the connected Playwright hand. It shares
tabs, input and browser policy with that runtime. Viewport changes use
`PUT /api/browser/viewport`.

[External browser sessions](docs/external-browser-sessions.md) documents Legacy
MCP Bridge behavior; it is historical context rather than this V1 deployment contract.

## OAuth sessions

User authorization and token lifecycle are managed by the external OIDC provider. Briareus records
application invocation audit, not a second OAuth session authority.

## Observability and infrastructure

SigNoz and Coolify are independent read-only MCP providers:
`/observability/signoz/mcp` and `/infrastructure/coolify/mcp`. Connect each needed
provider separately. Their source-list and data tools use provider-specific
names and explicit account selectors; no aggregate `observability_sources` remains.

SigNoz provides logs, traces, metrics/query access, observed-service and field
discovery. Coolify provides safe application/deployment/storage metadata and
variable names/flags, never variable values or deployment mutation tools. Account
credentials remain encrypted in Control Panel API and are resolved by each provider.

Hot-path telemetry distinguishes cache/Control Panel API access, backend MCP session reuse, provider
HTTP latency and connection-pool wait, and Control Panel API repository operations. Control Panel API audit
delivery is batched through a bounded in-memory queue: each MCP call remains an individual audit
record and metric event, while short batches share one internal HTTP request and one SQL
transaction. Sensitive arguments, credentials, authorization headers, full request URLs and
cache keys are not exported as span attributes.
