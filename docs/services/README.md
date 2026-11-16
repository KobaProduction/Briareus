# Core services (not MCP Hands)

This directory owns the **control plane and shared infrastructure** of V1. Read only the relevant owner page before editing that component.

| Service | Responsibility | Owner contract and source |
| --- | --- | --- |
| Control Panel UI | SPA, OIDC client state, pages and operator workflows | [Control Panel](control-panel.md), [UI source](../../services/control-panel/ui/README.md) |
| Control Panel API | Accounts, encrypted credentials, Alembic, bootstrap and realtime | [Control Panel](control-panel.md), [API source](../../services/control-panel/api/README.md) |
| Gateway | Public routing, token verification, MCP metadata, proxy lifecycle | [Gateway](gateway.md), [Gateway source](../../services/gateway/README.md) |
| Dependencies | PostgreSQL, Valkey, Chromium and persistent backing services | [Dependencies](dependencies.md), [Dependencies source](../../services/dependencies/README.md) |

These are **four separate Coolify resources** on the same node environment network. Do not introduce a legacy `management` container, `auth` container, shared root bridge or separate Curl runtime. The Control Panel **API** contains the account-management capability; the term "management" in a retained protocol field is not a standalone service.

MCP providers, including read-only Coolify/SigNoz access, belong in [Hands](../hands/README.md). For deployment settings and lifecycle, use [operations](../operations/README.md), not a Hand's internal README as the global authority.
