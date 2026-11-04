# Components

| Owner | Responsibility |
| --- | --- |
| Control Panel UI | Browser frontend and operator UI |
| Control Panel API | Accounts, credentials, PostgreSQL/Alembic, human sessions, hosted MCP OAuth |
| Gateway | Public edge, resource metadata, authenticated routing |
| Dependencies | PostgreSQL, Valkey, persistent Chromium, pinned Ghidra engine/bridge |
| GitHub / GitLab | Repository and collaboration providers |
| Files | Shared workspace operations and upload ingress |
| Web | HTTP, persistent browser and DevTools |
| Terminal | Non-root persistent execution and PTY jobs |
| Analysis / Ghidra | Structured analysis and adapter to external Ghidra MCP |
| Observability | Read-only SigNoz and Coolify adapters |
| Shared capabilities | Reusable contracts, clients and runtime components |

The source map is [the repository layout](../../README.md#repository-layout).
Services communicate through runtime protocols and do not import another
service's source. Shared packages are copied whole into their consuming images.
Each Python deployment owns its dependencies and frozen lock. ZITADEL stays
external; the OAuth facade runs inside Control Panel API.
