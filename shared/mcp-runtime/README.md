# Shared private MCP HTTP runtime for Rust Hands

`briareus-mcp-runtime` supplies the reusable `rmcp` Streamable HTTP service,
private Host/Origin restrictions and `/health` / `/health/discovery` routes.
The Hand injects its `ServiceIdentity` and environment. SigNoz is the first
consumer, not an embedded special case.

This is private Hand infrastructure, **not** the public OAuth resource server
or Gateway. Frontend session authentication and provider routing belong to
Gateway and are tested separately.
