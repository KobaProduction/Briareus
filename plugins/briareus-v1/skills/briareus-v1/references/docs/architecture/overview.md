# V1 architecture overview

**Current owner map:** [Core architecture](../core/runtime.md). This page is a short navigation/diagram for the existing architecture, not a second competing requirements document.

```text
Browser / MCP clients --> external OIDC authority
          |
          | Bearer token / MCP resource metadata
          v
        Gateway  --> Control Panel UI /admin/*
           |     --> Control Panel API /api/* --> PostgreSQL
           |                    |                 Valkey
           |                    +-- encrypted provider accounts/discovery
           |
           +---- independent MCP Hands (11 catalog entries, optional)
                  | Server (files + terminal/jobs) --> shared /workspace
                  | Playwright --> persistent Chromium (Dependencies)
                  | GitHub / GitLab
                  | Analyzer-R / Analyzer G / radare2 / Ghidra adapter
                  | SigNoz (read) / Coolify (scoped operations)
                  | Serena (optional, intentionally stopped)
```

**Four core resources:** Control Panel UI, API, Gateway, Dependencies. **Eleven possible Hands** are enumerated in [`deploy/services.json`](../../deploy/services.json). No separate Management, Curl, Files/Terminal, local OAuth or root aggregate MCP Bridge application exists.

OIDC and node access: [provider](../oidc.md), [MCP OAuth](../oauth-chatgpt.md). Per-owner details: [services](../services/README.md), [Hands](../hands/README.md), [deployment](../operations/deployment.md).

The separate `v2` branch defines an autonomous Node and Infrastructure/Hands system with its own access/storage contracts; **do not mix it into this V1 diagram**.
