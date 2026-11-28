# Gateway Rust — V1 replacement candidate

**Transport-only cutover candidate.** The active production Gateway is
still Python. This branch preserves the existing provider registrations,
browser PKCE, API-owned browser configuration and node provisioning,
credential names, OIDC scope list, node roles and private API contract.
No new provider registration or secret is needed. The separate confidential
browser-session implementation is intentionally not part of this release.

## Implemented and locally tested

- HTTP reverse proxies for `/admin/*` (UI) and `/api/*` (Control Panel API),
  preserving body, query, auth headers, cookies, streaming, redirects and
  forwarded headers. Separate `Set-Cookie` fields are preserved rather than
  reproducing Python's merged output.
- Exact external OIDC resource metadata for registered/discovered MCP paths;
  JWT verification for all seven configured Python algorithms via shared Rust
  OIDC, signature, issuer, audience,
  expiry, client identity and node role, including both list and organization
  grants. Optional RFC 7662 opaque-token introspection uses a 5-minute issuer
  metadata cache and bounded SHA-256-keyed 30-second principal cache.
- Dynamic node-scoped Valkey discovery, private readiness probe with strict
  service/environment match, 5-second snapshot, no stale availability on
  discovery failure; no database or identity authority inside Gateway.
- Official `rmcp` per-provider Streamable HTTP facade with separate frontend
  sessions and **two reusable backend MCP connections per Hand**, including
  `initialize`, tools, typed JSON schemas, resources and prompts. All MCP
  requests authenticate the caller before looking up session state. Each
  session belongs to the verified subject and OAuth client, independently
  of bearer rotation. The limit is 128 concurrent frontend sessions per
  Hand; explicit deletion releases capacity. Response delivery and standalone
  SSE are bounded by the admitting token's expiry. Duplicate credentials or
  session headers are rejected. The public Bearer never reaches a private
  Hand. A changed backend identity/URL creates a fresh frontend and backend
  pool. Only an interrupted backend initialize response permits one bounded
  retry within the existing connection timeout; Gateway does not replay a
  dispatched business request. The existing private Control Panel MCP timeout
  policy is read with the unchanged service credential and a five-second
  local cache; zero remains unlimited, and metadata calls retain at least
  thirty seconds. API lookup failure uses the existing zero fallback.
- Browser realtime, operator and CDP WebSocket relays with exact Origin,
  `briareus.v1` plus the existing bearer subprotocol, private Control Panel
  forwarding, text/binary messages, bounded payload size and expiry-triggered
  close.

The tests call isolated local Python FastMCP providers and an RSA/JWKS/OIDC
fixture; the Python Gateway's live `ServiceMcpRoutes` is used as the reference
for schema and result parity. No real account tokens or production services
are accessed. Rust tests and Clippy run without Docker.

## Cutover acceptance

Run the focused native smoke checks and required publication gate. Before
changing the live edge, validate the actual Coolify parser and image,
existing OIDC configuration and discovery, the existing panel identity
endpoint and MCP admission. Keep the current API/UI images and all
credentials unchanged. Preserve the Python Gateway image, effective Compose
configuration and route/alias ownership for rollback. Validate one node
before migrating another. The remaining extended protocol, telemetry and
load coverage is deferred, not passed.

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
.venv/bin/python services/gateway-rust/tests/check_private_preview.py -q
.venv/bin/python services/gateway-rust/tests/check_concurrent_mcp_sessions.py -q
```

`deploy/services.json` continues to describe only the existing Python public
Gateway. Its real saved Watch Paths were checked: they contain the Python
Gateway and explicitly consumed Python shared packages, **not**
`services/gateway-rust/**` or native shared crate paths. An isolated Rust source push
must never be mistaken for a production Gateway deployment receipt.

## Launch modes and packaging (not a production cutover)

One `Dockerfile` and generic `docker-compose.yaml` own the native image and
runtime configuration. `scripts/briareus_coolify.py` generates both
`docker-compose.coolify.yaml` and the isolated `docker-compose.preview.yaml`.
All three Compose entrypoints are included in source validation. The active
catalog and Python Watch Paths remain unchanged until verified promotion.

The native process requires exactly one of three modes:

- `RUST_GATEWAY_SHADOW_ONLY=true` with a loopback listener for synthetic tests.
- `GATEWAY_PRIVATE_PREVIEW=true` with the private container listener, existing
  OIDC, service authentication and Valkey configuration. No public ingress,
  host port or live Gateway alias is generated.
- `--public` is a fixed Compose command. The process requires HTTPS issuer
  and public origin, staging or production, port 8000, canonical private
  API/UI/Valkey endpoints and existing service authentication. JWT mode
  requires no client secret. Introspection mode uses the existing
  `OIDC_INTROSPECTION_CLIENT_ID` and `OIDC_INTROSPECTION_CLIENT_SECRET`.
  Preserve the existing `OIDC_SCOPES` and role policy exactly. No browser
  client or provisioning token is consumed by this Gateway.
  Coolify owns one `SERVICE_URL_GATEWAY_8000: /` route.

Both deployed modes run as a fixed non-root user with a read-only filesystem,
dropped capabilities and separate native image tags. SIGTERM/SIGINT stops
admission and drains for at most 20 seconds inside the 25-second Compose stop
grace. Completion of in-flight effects is not guaranteed after this deadline.

## Preview and controlled promotion

The generated preview uses the same native Dockerfile as the public
candidate. Select the verified compatibility source revision in the
existing stopped Preview, reuse the existing private Destination and
protected configuration, and never advertise a second public route.
The preview can use the deployed API/UI and Valkey for nonmutating smoke
checks because their identity protocol is unchanged. Do not invoke
mutating Hands or change role registrations during preview acceptance.

Promote the public candidate only after confirming the old image and
configuration can be restored. Keep exactly one public edge and one
private `gateway` alias per node. Preserve issuer, audience, role policy,
scope list, introspection credentials and existing API/UI. Test the actual
client's authenticated MCP and panel flows after promotion; roll back on
failed readiness, authorization or critical routing. Do not rotate or
delete old provider credentials during this transport cutover.

The public deployment catalog remains on Python until verified promotion.
