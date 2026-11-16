# Briareus V1 documentation

Use these **active, owner-specific entrypoints** instead of reading every Markdown file:

| Domain | Canonical documentation |
| --- | --- |
| Core runtime and architecture | [Core](core/README.md) |
| Control Panel UI, API, Gateway, Dependencies | [Services](services/README.md) |
| Independent MCP providers | [Hands](hands/README.md) |
| Deployment, tests, configuration, Git/worktrees | [Operations](operations/README.md) |
| Architecture decisions | [ADRs](decisions/README.md) |
| Historical migration/refactoring material | [History](history/README.md) |

Specialized references remain available where relevant: [repository map](repository-map.md), [external OIDC](oidc.md), [MCP OAuth](oauth-chatgpt.md), [MCP connection names/icons](mcp-connections.md), [GitHub history operations](github-history-surface.md), [GitHub Actions](github-actions.md), and [file-transfer contract](file-service.md).

The **source catalog**, not a handwritten Hand count, determines supported resources. Read the owner service README for implementation details, [operations](operations/README.md) before changes to infrastructure, and [the root agent instructions](../AGENTS.md) before development.

For `v2`, switch to that branch and use **its** `AGENTS.md` and `docs/README.md`. V2 requirements are not V1 deployment instructions.
