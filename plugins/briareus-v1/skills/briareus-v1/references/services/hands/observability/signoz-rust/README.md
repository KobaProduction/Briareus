# SigNoz Rust Hand — V1 private backend

**Live on `tambov` since the 17 November 2026 cutover:** Rust serves the
existing `/observability/signoz/mcp` Gateway route through the private
`signoz-mcp-hand` DNS alias. All eight read-only tools passed authenticated
Gateway calls; Control Panel HTTP-accepted its invocation audit. The former
Python SigNoz container is **stopped, retained for rollback**, and its
Docker restart policy is disabled. The public Gateway and Control Panel
implementations were not changed.

The running Coolify resource is `Hand / SigNoz Rust Preview` (UUID
`mc69ggckxx68aub0d3hmmjbt`) in the existing `tambov` environment.
Despite the historical preview name, its current private service alias is
the active production SigNoz backend. This remains an explicit **source
migration boundary**: `deploy/services.json` now names this Rust backend; the stopped Python
Coolify resource is an image-only rollback asset and must not be rebuilt.
The running Rust resource retains its pre-migration Coolify base directory
and pilot Compose entrypoint until the saved application settings can be
migrated safely. Never start the Python image while Rust owns `signoz-mcp-hand`,
or two containers will compete for the same private DNS name.
A verified rollback drill is still outstanding.

## Current scope

The Rust binary serves `GET /health` and Streamable HTTP `/mcp` with eight
SigNoz tool names identical to the Python service. SigNoz query construction
lives in `src/signoz.rs`. Shared account resolution, bounded HTTP/TLS
transport and credential-safe errors live in `shared/hand-core`.
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
and descriptive metadata parity, public OIDC renewal paths and
production OpenTelemetry collector acceptance.

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

The generic `AuditReporter` in `shared/hand-core` sends audit event batches
to the same Control Panel `POST /internal/events/batch` endpoint used by Python.
It runs a non-blocking bounded queue (`RUST_MCP_AUDIT_QUEUE_ENTRIES`, default 64,
valid 1–256), batches at most 32 events within a 50 ms window, and attempts
a final bounded flush when the server shuts down cleanly. Queue overflow and
delivery failures are counted and logged as rate-limited safe categories, not
provider messages. Failure to write an audit does not turn a read-only MCP
query into a tool error, matching Python's best-effort audit semantics.
The private-only diagnostic `GET /health/observability` returns
`enabled`, `queued_events`, `accepted_events`, `accepted_batches`,
`failed_batches`, `dropped_events` and `otel_enabled` without accounts,
arguments, results or tokens. `accepted_*` increments only when Control Panel
answers HTTP 204; it proves successful HTTP acceptance, **not independent
durable DB verification**. Do not attach this endpoint to a public route.

`RUST_MCP_AUDIT_ENABLED` defaults to false for local/isolated tests, but
is **enabled on the active Rust Coolify resource** with the existing private
Control Panel service token. All eight Rust
SigNoz calls are instrumented. Events carry module, tool, selected account,
outcome, safe error category and duration. They **never** copy raw SigNoz logs,
traces, provider responses, query filters, payloads or credentials into
Management audit history. This deliberately reduces detail compared with
Python's redacted payload audit. Bad/missing MCP input that fails schema
parsing before dispatch remains an additional audit-parity gap.

## Low-memory OpenTelemetry (opt-in)

The shared Rust `Telemetry` module uses the official OpenTelemetry SDK
(v0.33.1), with OTLP/HTTP protobuf exporters for traces, metrics and
failure-only logs. The export endpoint is `OTEL_ENDPOINT`, optionally with
a protected runtime-only `OTEL_BEARER_TOKEN`; an **empty endpoint disables
all exporters and their queues/worker threads**. The isolated preview has
`OTEL_SERVICE_NAME=briareus-signoz-rust-preview`, separate from the
production Python service. `OTEL_NAMESPACE` defaults to `briareus`.

To control RAM, the exporter queues are explicitly limited to 64 spans and
32 log records, sending at most 16 per batch. Tool spans include their actual
duration and only bounded, static tool/outcome attributes; tool counters,
failures, caller rejections, latency histograms, runtime-start counter and
runtime-up gauge are exported. `OTEL_METRIC_EXPORT_INTERVAL_MS` defaults to
30000 (allowed range 1000–300000). Collector requests have a 3-second
timeout and a 1-MiB payload ceiling, reuse at most two idle connections,
and reject HTTP redirects **even when a collector bearer token is set**.
Never copy arguments, provider response bodies, credentials, or error messages
into OTLP telemetry.

The official blocking OTLP client is initialized on a Tokio blocking worker
to avoid nested Tokio runtime drop panics; shutdown is also off the Tokio
worker. Offline tests verify all three signals with a synthetic collector,
no synthetic secrets in payloads, and no bearer forwarding to a redirect
destination. **These tests are not proof that a production collector accepts
real data.** Explicitly configure the collector via protected Coolify settings
and validate consumption before declaring observability equivalence.
The current cutover is serving calls with `otel_enabled=false`; this is
an explicitly outstanding telemetry regression, not a claim of parity. Full parent/traceparent context
propagation and Python-equivalent audit for schema-invalid tool calls are
not yet implemented.

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
`cargo test --offline --manifest-path ../../../../shared/hand-core/Cargo.toml`.
The MCP unit test performs a real loopback Streamable HTTP handshake and
inspects tool discovery and typed input errors. SigNoz-specific tests
validate payloads and timestamp normalization. The separate offline [Python-to-Rust parity harness](https://github.com/KobaProduction/Briareus/blob/v1/services/hands/observability/signoz-rust/tests/check_mcp_parity.py)
uses a real MCP client with mock Control Panel/SigNoz servers, comparing
all eight tools and raw log/trace query payloads to the Python implementation.
After cargo build, run it with the V1 Python test environment:

```sh
.venv/bin/python services/hands/observability/signoz-rust/tests/check_mcp_parity.py -v
```

The harness deliberately avoids the V1 Python aggregate `test_*.py` discovery:
it needs a prebuilt Rust binary and is instead required by its own
path-scoped Rust pilot CI. It has no connection to production credentials.

## V1 private discovery for cutover

Set `RUST_MCP_DISCOVERY_ENABLED=true` only after injecting a valid protected
`VALKEY_PASSWORD` from the existing private node environment. The bounded
Rust registry publishes the identical SigNoz inventory and short 20-second
Valkey lease every five seconds, authenticated with `VALKEY_USERNAME`, and
withdraws the instance lease on SIGTERM. `GET /health/discovery` returns
the Python-compatible service/environment/ready JSON. Valkey outage does not
bypass the public Gateway authorization boundary. The default local preview
has registration disabled; the active Coolify Rust resource explicitly sets
`RUST_MCP_DISCOVERY_ENABLED=true` and `RUST_SIGNOZ_SERVICE_ALIAS=signoz-mcp-hand`.
The DNS alias was verified again after an ordinary Coolify redeploy.
Never enable the same alias on the stopped Python resource simultaneously.
For rollback, stop Rust first and only then start Python.

## Post-cutover acceptance and rollback

After the cutover, all eight tools returned expected read-only results through
the authenticated Gateway MCP surface. Discovery was confirmed by a single
live Valkey lease and `/health/discovery` from the Gateway network; audit
reported accepted HTTP 204 batches with no failures/drops. The Rust container
has a 256 MiB memory cgroup cap, non-root read-only filesystem, no published
ports and `restart: unless-stopped`. The Python container remains stopped.

For rollback, stop the Rust Coolify resource/container **before** starting
the previously retained Python resource, restore the Python restart policy,
then verify Valkey lease, private DNS and authenticated Gateway MCP tools.
Do not run both resources with the same alias. Remaining follow-ups include
canonical source catalog migration, real OTLP collector activation and
traceparent propagation, Python-equivalent pre-dispatch rejection audit,
OIDC refresh scenarios and a tested rollback operation.
No database migration or Gateway code change was part of the cutover.

## Historical preview entrypoint and canonical private image

The owner-local `Dockerfile.pilot` and `docker-compose.pilot.yaml` are
**historically opt-in deployment inputs**. The separate Rust application
is now the selected private SigNoz backend on `tambov`, and its manifest is now the canonical `signoz` entry in
`deploy/services.json`. Its running Coolify resource still uses the
pre-migration pilot entrypoint until those saved settings are changed.
The public Gateway service catalog ID and route are unchanged.

The Compose candidate attaches only to the existing Briareus **private**
network (`briareus-v1-${DEPLOYMENT_ENVIRONMENT}`), which must exist as a
Docker network in the selected Coolify Destination. In the `production`
environment on `tambov`, the verified network is `briareus-v1-production`.
This is the existing private destination network; no new network should be
created solely for the pilot. The preview uses no public Gateway mapping.

Both the canonical and pilot builds have **no published host ports** and run non-root with a read-only
root filesystem and dropped Linux capabilities, and has a configurable
`RUST_SIGNOZ_PILOT_MEMORY_LIMIT` (256 MiB default). Its private
`BRIAREUS_SERVICE_TOKEN` must be injected through the existing protected
resource mechanism; no secret is copied into the image.

The container deliberately sets `BIND_HOST=0.0.0.0` **inside its isolated
network namespace only**, while the local binary defaults to loopback.
Never use that bind setting with host networking or a published port.
The Dockerfile-specific ignore file restricts its build context to the
Rust Signoz owner and its focused shared crate.

The offline suite does not prove real deployment acceptance. Re-check actual
Coolify revisions, private topology, account grants, audit delivery and
Gateway tools after any new deployment. Production collector delivery
and a rehearsed rollback remain explicitly unverified.
