# SigNoz and Coolify Hands — read-only observation

**Catalog:** `signoz`, `coolify`. **Sources:** [SigNoz](../../services/hands/observability/signoz/README.md), [Coolify](../../services/hands/infrastructure/coolify/README.md).

SigNoz exposes telemetry/service/field discovery and queries at `/observability/signoz/mcp`. Coolify exposes safe deployment/resource metadata at `/infrastructure/coolify/mcp`. The Hands are **independent read-oriented MCP adapters**: no combined Observability MCP exists.

Credentials and account selections belong to the Control Panel API. Metadata, variable names and selected safe fields are not permission to read secrets. Coolify log access is available only when the selected Coolify token is explicitly authorized for that endpoint; it may contain sensitive operational text and is redacted on a best-effort basis. The Coolify Hand does **not** provide generic deploy/restart/delete mutation tools — such changes require separately authorized infrastructure mechanisms.

SigNoz logs, traces and metrics are observations, not proof that a source revision or every user flow passed. Handle expected caller errors, provider failures and unhealthy runtime separately.

See [runtime](../core/runtime.md), [deployment](../operations/deployment.md), and the owner READMEs linked above.
