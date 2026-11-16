# Architecture Decision Records — V1

ADRs explain *why* decisions were made; they do not replace current service owner contracts.

| Decision | Status | Current authority |
| --- | --- | --- |
| [0001: Legacy Management SQLite ownership](0001-account-management.md) | **Superseded** | [Control Panel API](../services/control-panel.md) |
| [0002: Separate Terminal MVP](0002-terminal-workspaces.md) | **Superseded** | [Server Hand](../hands/server.md) |
| [0003: Independent V1 core and Hands](0003-v1-service-ownership.md) | **Accepted** | [Core runtime](../core/runtime.md) |

The previous ADRs are retained **only for rationale and provenance**. Their old component names, database rules and routes must not be used for implementation or deployment.

Add an ADR when a new owner boundary, security decision, persistence model or runtime protocol would otherwise be repeatedly re-litigated. Include status, context, decision, consequences and links to the canonical owner documentation. V2 decisions belong on the `v2` branch.
