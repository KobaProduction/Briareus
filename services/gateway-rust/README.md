# Gateway Rust — V1 local shadow migration

**Production is still the Python Gateway.** This is a standalone, unexposed
Rust process for contract testing. It requires `RUST_GATEWAY_SHADOW_ONLY=true`
and refuses to bind outside loopback; it has **no Compose resource, public port,
deployment catalog entry, or Coolify Watch Paths**. Do not deploy it as the
public Gateway before all remaining parity and rollback gates pass.

## Implemented and locally tested

- HTTP reverse proxies for `/admin/*` (UI) and `/api/*` (Control Panel API),
  preserving body, query, auth headers, cookies, streaming, redirects and
  forwarded headers. Separate `Set-Cookie` fields are preserved rather than
  reproducing Python's merged output.
- Exact external OIDC resource metadata for registered/discovered MCP paths;
  RSA JWT verification via shared Rust OIDC, signature, issuer, audience,
  expiry, client identity and node role, including both list and organization
  grants. Optional RFC 7662 opaque-token introspection uses a 5-minute issuer
  metadata cache and bounded SHA-256-keyed 30-second principal cache.
- Dynamic node-scoped Valkey discovery, private readiness probe with strict
  service/environment match, 5-second snapshot, no stale availability on
  discovery failure; no database or identity authority inside Gateway.
- Official `rmcp` per-provider Streamable HTTP facade with separate frontend
  sessions and **two reusable backend MCP connections per Hand**, including
  `initialize`, tools, typed JSON schemas, resources and prompts. All MCP
  requests authenticate the caller before looking up session state; the
  public Bearer is never forwarded to a private Hand. A changed backend
  identity/URL creates a fresh frontend and backend pool.
- Browser realtime, operator and CDP WebSocket relays with exact Origin,
  `briareus.v1` plus one bearer subprotocol, private Control Panel forwarding,
  text/binary messages, bounded payload size and expiry-triggered close.

The tests call isolated local Python FastMCP providers and an RSA/JWKS/OIDC
fixture; the Python Gateway's live `ServiceMcpRoutes` is used as the reference
for schema and result parity. No real account tokens or production services
are accessed. Rust tests and Clippy run without Docker.

## Required before any public cutover

1. Confirm all MCP protocol versions, keepalive/reconnect, cancellation,
   streaming event delivery, prompt/input-required, tool-list changes,
   resource subscription, custom resource and error semantics against Python
   under long-lived concurrent sessions. Verify authorization challenges,
   metadata and host/origin errors against real MCP clients.
2. OIDC validation must cover the full configured Python algorithm allowlist,
   including **ES512** (currently unsupported in the Rust JWT backend); test
   issuer/JWKS rotation, introspection invalidation and browser reauthorization.
3. Validate simultaneous browser WebSocket and MCP load, memory peak and
   failure isolation; add bounded, privacy-safe OpenTelemetry and safe audit
   without leaking bearer, provider response payloads or credentials.
4. Prepare a separate *private* Rust Gateway preview, verify saved Coolify
   configuration and Watch Paths, perform fully authenticated client acceptance
   and a rehearsed, immediate rollback. Do not rewrite the public Gateway
   resource in place during development.

## Local test commands (from repository root)

```sh
cargo fmt --check --manifest-path services/gateway-rust/Cargo.toml
cargo test --locked --manifest-path services/gateway-rust/Cargo.toml
cargo clippy --locked --all-targets --manifest-path services/gateway-rust/Cargo.toml -- -D warnings
cargo build --locked --manifest-path services/gateway-rust/Cargo.toml
.venv/bin/ruff check services/gateway-rust/tests
.venv/bin/python services/gateway-rust/tests/check_http_parity.py -q
.venv/bin/python services/gateway-rust/tests/check_oidc_parity.py -q
.venv/bin/python services/gateway-rust/tests/check_introspection_parity.py -q
.venv/bin/python services/gateway-rust/tests/check_discovery_parity.py -q
.venv/bin/python services/gateway-rust/tests/check_mcp_parity.py -q
.venv/bin/python services/gateway-rust/tests/check_python_mcp_parity.py -q
.venv/bin/python services/gateway-rust/tests/check_websocket_parity.py -q
.venv/bin/python services/gateway-rust/tests/check_catalog_parity.py -q
```

`deploy/services.json` continues to describe only the existing Python public
Gateway. Its real saved Watch Paths were checked: they contain the Python
Gateway and explicitly consumed Python shared packages, **not**
`services/gateway-rust/**` or native shared crate paths. An isolated Rust source push
must never be mistaken for a production Gateway deployment receipt.

## Isolated private-network preview (not a production cutover)

`Dockerfile.preview` and `docker-compose.preview.yaml` define a **separate**
Coolify application candidate; they are deliberately excluded from
`deploy/services.json` and the public Python Gateway's Watch Paths.
The native process requires exactly one of two modes:

- `RUST_GATEWAY_SHADOW_ONLY=true` with a loopback listener for synthetic tests.
- `GATEWAY_PRIVATE_PREVIEW=true` with `BIND_HOST=0.0.0.0`, a configured
  external OIDC verifier and Valkey discovery. The preview rejects fixture
  target overrides and **cannot** become the public Gateway through a mode
  switch alone. This listen address is safe **only** in the isolated private
  container network defined below; never bind it to a host interface.

For a separate Coolify preview, use the existing node's **private Destination**,
set Base Directory `/services/gateway-rust` and Compose Location
`/docker-compose.preview.yaml`, and scope Watch Paths to the Gateway Rust owner,
`shared/service-discovery/**` and `shared/oidc-verifier/**`. Do **not** add a
public domain, Traefik router, published host port, `gateway` DNS alias or
`SERVICE_URL_GATEWAY_8000`. Do not change the existing Python Gateway resource.
Confirm actual Destination/network and source revision independently; the
source Compose intentionally has no published ports. Required OIDC/node/Valkey
values come from the selected node's existing protected configuration. The
preview is **not a read-only sandbox**: authenticated API requests, mutating
MCP tools and Browser Operator traffic can change real backend state. Only
trusted operators may call it, using explicitly approved test identities and
non-destructive operations; do not run exploratory writes against production
accounts, browser profiles or data. It is not a new public OAuth resource.
`GET /health` establishes process readiness, **not** end-to-end MCP
authorization, safe read-only semantics or parity.

The local safety and Compose contracts are in
`tests/check_private_preview.py`. `tests/check_concurrent_mcp_sessions.py`
checks six independent frontend sessions, 48 concurrent MCP calls, deletion
isolation and fresh bearer checks against synthetic provider fixtures.
Neither suite deploys resources or accesses live credentials. Promotion needs separate load/OIDC/observability acceptance and
an independently rehearsed rollback. The Rust image leaves the Python Gateway
untouched and has a fixed non-root, read-only, capability-dropped runtime.

## Canonical MCP Host/Origin policy

Like the Python Gateway, the native Gateway accepts the canonical public URL
from `SERVICE_URL_GATEWAY` (managed Coolify deployment) or, for standalone
preview/shadow, `MCP_PUBLIC_BASE_URL`. It rejects insecure non-local HTTP,
paths, userinfo and ambiguous URL values. For MCP and OAuth resource-metadata
routes, it requires exactly one `Host` matching that URL's authority and
rejects supplied `Origin` values other than the exact origin. Ordinary HTTP
proxy routes retain their separate forwarding behavior. Synthetic tests set
`Host: briareus.example` explicitly, because the HTTP transport connects to
the fixture over loopback. No additional wildcard Host/Origin allowlists are
introduced.
