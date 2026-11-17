# V1 component responsibilities

This is a **catalog view**, not an independent architecture source. The live resource list is [`deploy/services.json`](../../deploy/services.json).

| Component | Responsibility | Documentation |
| --- | --- | --- |
| Control Panel UI | Browser SPA, OIDC client state and operator experience | [Service](../services/control-panel.md) |
| Control Panel API | Accounts, encrypted credentials, PostgreSQL/Alembic and administration | [Service](../services/control-panel.md) |
| Gateway | Public bearer/MCP routing and OAuth resource metadata | [Service](../services/gateway.md) |
| Dependencies | PostgreSQL, Valkey, persistent Chromium | [Service](../services/dependencies.md) |
| Server | File access, command execution and durable jobs | [Hand](../hands/server.md) |
| Playwright | Internal Chromium and external browser mode | [Hand](../hands/browser.md) |
| GitHub and GitLab | Source control with provider-scoped accounts | [Hand](../hands/source-control.md) |
| Analyzer-R, Analyzer G, radare2, Ghidra | Separate program-analysis providers and adapters | [Hands](../hands/analysis.md) |
| SigNoz and Coolify | Read-only SigNoz and scoped Coolify observation/operations | [Hands](../hands/telemetry.md) |
| Serena | Optional semantic tooling; not currently running | [Hand](../hands/semantic.md) |

The catalog contains **15 resources** (4 core + 11 Hands). This total is **not** a promise that all possible resources or external dependencies are deployed.

Shared libraries are not independent runtime resources; consumers import their focused packages. External OIDC and native Ghidra projects remain under separate ownership.
