# Briareus SigNoz MCP

Standalone SigNoz provider MCP in the observability group. Its `/mcp` endpoint exposes only signoz tools. Provider accounts and credentials are resolved by the private Control Panel client; this service does not access its database directly.

Deploy this owner with `docker-compose.yaml` or generated `docker-compose.coolify.yaml` on the node network. No other provider service is required. Common MCP middleware, provider-account caching, configuration, telemetry and ASGI hosting are reused from shared packages.


## Python fallback following Rust cutover

On `tambov`, the production Gateway's SigNoz route now uses the
[separate Rust Hand](../signoz-rust/README.md) at the original private
`signoz-mcp-hand` hostname. This Python resource is **stopped for rollback**
and must not be redeployed while the Rust resource owns that alias.
The Python source remains in the V1 deployment catalog pending canonical
source migration; the source catalog is not evidence of a currently running
Python SigNoz container. Follow the Rust owner's rollback order to avoid
conflicting network aliases.
