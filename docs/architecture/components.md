# Components

| Owner | Responsibility |
| --- | --- |
| Control Panel UI | Browser frontend and operator UI |
| Control Panel API | Accounts, credentials, PostgreSQL/Alembic, external OIDC token verification |
| Gateway | Public edge, resource metadata, authenticated routing |
| Dependencies | PostgreSQL, Valkey, persistent Chromium |
| GitHub / GitLab | Repository and collaboration providers |
| Server | Shared workspace files, upload ingress, terminal and PTY jobs |
| Web | HTTP, persistent browser and DevTools |
| Analysis / Ghidra | Structured analysis and adapter to external Ghidra MCP |
| Observability | Read-only SigNoz and Coolify adapters |
| Shared capabilities | Reusable contracts, clients and runtime components |

The source map is [the repository layout](../../README.md#repository-layout).
Services communicate through runtime protocols and do not import another
service's source. Shared packages are copied whole into their consuming images.
Each Python deployment owns its dependencies and frozen lock. The OpenID provider
and Ghidra MCP remain external. Briareus does not host an OAuth issuer or facade.
