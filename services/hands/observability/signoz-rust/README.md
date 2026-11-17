# SigNoz Rust Hand — parallel pilot

This is an **experimental, read-only MCP implementation** alongside the
existing Python SigNoz Hand, not a replacement or an extra production catalog
resource. The Python Hand, its Gateway route and deployment remain unchanged.
The pilot is not registered in Valkey discovery or connected to the public
Gateway. Never point the existing `/observability/signoz/mcp` route at it
before independent parity and consumer acceptance.

## Current scope

The Rust binary serves `GET /health` and Streamable HTTP `/mcp` with eight
SigNoz tool names identical to the Python service. SigNoz query construction
lives in `src/signoz.rs`. Shared account resolution, bounded HTTP/TLS
transport and credential-safe errors live in `shared/rust/hand-core`.
The Control Panel API remains the credential owner; direct database access
and local storage of provider secrets are deliberately absent.

### MCP result compatibility

`signoz_sources` and `signoz_connection` expose their ordinary JSON objects
directly in `structuredContent`, matching the Python Hand. The other six
`JsonValue` tools expose the provider payload as `structuredContent.result`
(the Python/FastMCP output schema uses `x-fastmcp-wrap-result`), while the
text fallback remains the **unwrapped** provider JSON. Both views and
their matching Python `tools/list` output schemas are tested against synthetic
fixtures. A provider response envelope must not be silently flattened into
the MCP structured result. Remaining cutover gates include full input schema
and descriptive metadata parity, Gateway discovery, audit and OpenTelemetry.

`CONTROL_PANEL_URL` defaults to `http://control-panel-api:8000`, and
`BRIAREUS_SERVICE_TOKEN` is **required**. A missing token fails startup.
`PORT` defaults to `18081`, while `BIND_HOST` defaults to `127.0.0.1`.
`RUST_PROVIDER_HTTP_CACHE_ENTRIES` controls the **process-local, bounded**
provider HTTP connection pool (default 32 entries; 0 disables; maximum 256).
Every MCP call still resolves and validates the account through Control Panel:
account-resolution results, grants and revocation decisions are **not** cached.
Changing the credential, revision, provider URL or TLS settings discards its
previous pooled client. Auth headers and credentials remain in process RAM
while a pooled client is retained; they are never written to disk.

## Bounded invocation audit (opt-in for preview)

The generic `AuditReporter` in `shared/rust/hand-core` sends audit event batches
to the same Control Panel `POST /internal/events/batch` endpoint used by Python.
It runs a non-blocking bounded queue (`RUST_MCP_AUDIT_QUEUE_ENTRIES`, default 64,
valid 1–256), batches at most 32 events within a 50 ms window, and attempts
a final bounded flush when the server shuts down cleanly. Queue overflow and
delivery failures are counted and logged as rate-limited safe categories, not
provider messages. Failure to write an audit does not turn a read-only MCP
query into a tool error, matching Python's best-effort audit semantics.

`RUST_MCP_AUDIT_ENABLED` is **false by default for the shadow preview**; a
private acceptance resource may explicitly enable it after verifying the
Control Panel service token, destination and audit scope. All eight Rust
SigNoz calls are instrumented. Events carry module, tool, selected account,
outcome, safe error category and duration. They **never** copy raw SigNoz logs,
traces, provider responses, query filters, payloads or credentials into
Management audit history. This deliberately reduces detail compared with
Python's redacted payload audit. Bad/missing MCP input that fails schema
parsing before dispatch remains an additional audit-parity gap.

Only for an isolated private-network container, set `BIND_HOST=0.0.0.0`
and explicitly scope `PRIVATE_MCP_ALLOWED_HOSTS` to its private service
aliases and `PRIVATE_MCP_ALLOWED_ORIGINS` to trusted origins. Never publish
the direct private MCP listener on a public network. All credentials must
come from runtime secrets rather than source or Compose files.

## Local checks without Docker

From this directory with Rust 1.88+ (the checked-in lockfile is mandatory):

```sh
cargo fmt --all -- --check
cargo clippy --offline --locked --all-targets -- -D warnings
cargo test --offline --locked
cargo build --offline --locked
```

The shared crate can be tested separately with
`cargo test --offline --manifest-path ../../../../shared/rust/hand-core/Cargo.toml`.
The MCP unit test performs a real loopback Streamable HTTP handshake and
inspects tool discovery and typed input errors. SigNoz-specific tests
validate payloads and timestamp normalization. The separate offline [Python-to-Rust parity harness](tests/check_mcp_parity.py)
uses a real MCP client with mock Control Panel/SigNoz servers, comparing
all eight tools and raw log/trace query payloads to the Python implementation.
After cargo build, run it with the V1 Python test environment:

```sh
.venv/bin/python services/hands/observability/signoz-rust/tests/check_mcp_parity.py -v
```

The harness deliberately avoids the V1 Python aggregate `test_*.py` discovery:
it needs a prebuilt Rust binary and is instead required by its own
path-scoped Rust pilot CI. It has no connection to production credentials.

## Before any live shadow rollout

Required gates still include credential-resolution and provider-error
contract tests; exact Python/Rust schemas and response parity; read-only
authorization; OpenTelemetry and private discovery behavior; an isolated
private-network deployment; and resource/latency comparisons under the
same workload. No automatic cutover, public Gateway registration or
removal of the Python service is implemented by this pilot.

## Optional isolated private-network shadow image

The owner-local `Dockerfile.pilot` and `docker-compose.pilot.yaml` are
**opt-in deployment inputs**, not running resources. They are intentionally
absent from `deploy/services.json`, existing Coolify resources and the
Gateway catalog. A separate application may be approved after validating
image build, bind/interface policy and existing secret delivery.

The Compose candidate attaches only to the existing Briareus **private**
network (`briareus-v1-${DEPLOYMENT_ENVIRONMENT}`), which must exist as a
Docker network in the selected Coolify Destination. In the `production`
environment on `tambov`, the verified network is `briareus-v1-production`.
This is the existing private destination network; no new network should be
created solely for the pilot. The preview uses no public Gateway mapping.

The candidate has **no published host ports**, runs non-root with a read-only
root filesystem and dropped Linux capabilities, and has a configurable
`RUST_SIGNOZ_PILOT_MEMORY_LIMIT` (256 MiB default). Its private
`BRIAREUS_SERVICE_TOKEN` must be injected through the existing protected
resource mechanism; no secret is copied into the image.

The container deliberately sets `BIND_HOST=0.0.0.0` **inside its isolated
network namespace only**, while the local binary defaults to loopback.
Never use that bind setting with host networking or a published port.
The Dockerfile-specific ignore file restricts its build context to the
Rust Signoz owner and its focused shared crate.

**No Docker image or live shadow deployment is accepted by the offline
test suite.** Manual acceptance must first verify actual Coolify
Base/Compose/Watch, private endpoints, account grants, real query parity,
telemetry/audit and rollback before creating/enabling any preview resource.
