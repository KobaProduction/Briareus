# Historical documentation — not deployment authority

Briareus previously used a combined MCP Bridge with its own OAuth, SQLite-based Management service and separate Files/Terminal/Curl interfaces. These are **not** the current V1 service architecture. The former `legacy-mcp-bridge` branch has been deleted from GitHub; do not deploy it or recreate its resources.

For retained historical context only:

- [Upstream MCP design audit](../refactoring/mcp-upstream-roadmap.md).
- [Backend/refactoring history](../refactoring/backend-control-plane-roadmap.md).
- [Older deployment handoff](../refactoring/deployment-dev-handoff.md).
- [Starlette Admin migration audit](../refactoring/starlette-admin-parity-audit.md).

These documents are superseded wherever they describe a local OAuth issuer, single Compose product, Management, Curl MCP, independent Files/Terminal endpoints or per-service state. They do not authorize modifying production volumes or deploying removed branches.

**Live V1 owner documentation:** [Core](../core/README.md), [Services](../services/README.md), [Hands](../hands/README.md), [Operations](../operations/README.md). V2 has its own branch and architecture docs.
