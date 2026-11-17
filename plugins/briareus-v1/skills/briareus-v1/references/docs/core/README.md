# Core architecture and source of truth — Briareus V1

This section describes the **current V1** architecture, not historical MCP Bridge or planned V2.

Read in this order:

1. [Runtime architecture and boundaries](runtime.md) — what exists, who owns it, and how services communicate.
   [Shared packages and discovery](shared-and-discovery.md) describes library owners, leases and Watch Path boundaries.
2. [Control Plane and infrastructure services](../services/README.md) — Control Panel UI, API, Gateway and Dependencies.
3. [MCP Hands](../hands/README.md) — independent capabilities exposed through Gateway.
4. [Operations](../operations/README.md) — deployment, validation, Git and workspace policy.

Specialized contracts: [external OIDC](../oidc.md), [MCP client OAuth](../oauth-chatgpt.md), [repository map](../repository-map.md), [architecture decisions](../decisions/README.md).

**Source hierarchy:** implementation and `deploy/services.json` determine what exists; the documented owner contracts explain intended behavior; generated Compose and saved Coolify settings require separate verification; a healthy container does not prove end-to-end acceptance. Historical documents cannot override the live V1 contract.

V1 is maintained on `v1`. V2 is a **different architecture** maintained on `v2`, with its own root `AGENTS.md` and documentation. Do not transplant V2's Infrastructure/Node/Project/session authority into V1 or treat V1's single-node control plane as the V2 target.
