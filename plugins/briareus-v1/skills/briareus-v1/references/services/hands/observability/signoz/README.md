# Briareus SigNoz MCP

Standalone SigNoz provider MCP in the observability group. Its `/mcp` endpoint exposes only signoz tools. Provider accounts and credentials are resolved by the private Control Panel client; this service does not access its database directly.

Deploy this owner with `docker-compose.yaml` or generated `docker-compose.coolify.yaml` on the node network. No other provider service is required. Common MCP middleware, provider-account caching, configuration, telemetry and ASGI hosting are reused from shared packages.
