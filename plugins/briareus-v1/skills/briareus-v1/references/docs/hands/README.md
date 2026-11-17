# MCP Hands — V1 capabilities

Each Hand is an **independently packaged, optionally deployed MCP application** under `services/hands/`. All Hands share the node's Gateway, externally verified user authority, typed discovery and private Control Panel account resolution as required. Each Hand has its own build/Compose/lock and owner-focused tests.

**Current catalog: 11 Hands**, grouped by responsibility:

| Family | Catalog entries | Focused documentation |
| --- | --- | --- |
| Files, terminal, jobs | `server` | [Server](server.md) |
| Browser | `playwright` | [Browser](browser.md) |
| Source control | `github`, `gitlab` | [Source control](source-control.md) |
| Program analysis | `analysis` (Analyzer-R), `analysis-g`, `ghidra`, `radare2` | [Analysis](analysis.md) |
| Observability and controlled infrastructure | `signoz`, `coolify` | [Telemetry & infrastructure](telemetry.md) |
| Semantic code tools | `serena` | [Serena](semantic.md) |

The catalog enumerates **possible deployments**, not their real-time health. On the current rollout Serena is intentionally stopped; do not infer availability from the source catalog or restart it during documentation work. Analyzer G and Analyzer-R are separate Hands, not one legacy Analysis stack.

The authoritative set and build watches are in [`deploy/services.json`](../../deploy/services.json). The public MCP connection instructions are [here](../mcp-connections.md); internal Hand `/mcp` endpoints must not be confused with Gateway's public path. Do not introduce independent Files, Terminal, Curl, root MCP bridge, aggregate Web/Observability or DevTools MCP services.
