# Shared Rust Hand foundation (pilot)

This directory is a **reusable library**, not a new MCP service or a persistence owner.

The crate `briareus-hand-core` provides the first Rust contracts for:

- `AccountDirectory`: asynchronous provider-scoped account listing and single-account resolution; clients depend on this interface rather than a Control Panel database.
- `PanelAccountDirectory`: HTTP adapter for the same private `/internal/accounts` routes already used by the Python Hands, including `BRIAREUS_SERVICE_TOKEN`.
- `ResolvedAccount`: typed provider account with a **safe public projection**. Credential fields never enter ordinary MCP responses.
- `JsonHttp`: bounded HTTP/JSON requests with configurable TLS validation, CA trust, request deadlines, an 8 MiB response ceiling and **redirects disabled** (preventing API keys from following untrusted 3xx locations).
- `HandError`: stable caller-facing error categories that do not interpolate upstream bodies or API credentials.
- `AuditReporter`: opt-in bounded asynchronous invocation audit to the Control
  Panel, with secret-omitting event summaries, 50 ms batches (up to 32),
  configurable capacity (1–256), safe failure counters and bounded shutdown
  flushing; a reusable facility for other Rust Hands, not an audit database.
- `ProviderHttpCache`: reusable bounded LRU of per-account, per-provider HTTP
  connection pools. Each caller must **first** re-resolve the Control Panel
  account; revision, credential, endpoint and TLS changes invalidate the pool.
  Zero-capacity mode disables reuse; no authorizations or encrypted account
  databases are persisted by this component.

Future Rust Hands should reuse this crate and implement their provider-specific API in their own source directory. They must **not** duplicate account databases, token issuance, identity authority or global session state. Reuse is limited to actual consumers; no parallel implementation is automatically routed by Gateway.

**Incomplete production contracts:** live invocation-audit acceptance and
pre-dispatch rejection coverage, OpenTelemetry/span context, live OIDC/Gateway
admission, service discovery/leases, shared Control Panel account/Valkey
cache parity and rollout/rollback acceptance.
The new provider HTTP pool reacts to account revisions, but is not a shared
account-authority cache. These require dedicated tests before replacing an existing Hand.

See the [parallel SigNoz pilot](../../../services/hands/observability/signoz-rust/README.md) for the first consumer. The reusable crate has no independently deployed container.
