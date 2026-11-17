# Briareus SigNoz MCP

Standalone SigNoz provider MCP in the observability group. Its `/mcp` endpoint exposes only signoz tools. Provider accounts and credentials are resolved by the private Control Panel client; this service does not access its database directly.

Deploy this owner with `docker-compose.yaml` or generated `docker-compose.coolify.yaml` on the node network. No other provider service is required. Common MCP middleware, provider-account caching, configuration, telemetry and ASGI hosting are reused from shared packages.


## Parallel Rust pilot (not a cutover)

An opt-in [SigNoz Rust implementation](../signoz-rust/README.md) is under
development with an isolated localhost MCP endpoint. It reuses the Python
Hand's eight tool contracts but is not registered in Gateway/Coolify and
does not modify this service. Its shared account/HTTP boundaries live in
[shared Rust Hand core](../../../../shared/rust/hand-core/README.md).
Only independently accepted parity, access, audit and rollback tests can
justify a future runtime switch.
