# Gateway — V1 public edge

**Owner:** `services/gateway`.

Gateway is the only public receiver of the node's HTTP/MCP routing. It serves Control Panel UI at `/admin/*`, proxies API at `/api/*` and forwards each available MCP Hand at its independent provider endpoint. It also exposes OAuth protected-resource metadata, validates external access tokens and enforces configured host/origin restrictions.

Provider discovery lives in shared libraries consumed by Gateway and API; it is **not another deployment**. A missing optional Hand must be distinguishable from authorization failure and must not disable other providers. Gateway never becomes a local OAuth issuer or credential store and has no root aggregate MCP Bridge endpoint.

For path contracts and resources see [MCP clients](../oauth-chatgpt.md), [runtime](../core/runtime.md), [Gateway source](../../services/gateway/README.md), and [deployment](../operations/deployment.md).
