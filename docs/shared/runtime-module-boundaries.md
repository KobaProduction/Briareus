# MCP module responsibility matrix

Every MCP module has its own catalog source directory, Compose and declared
tool/resource vocabulary. A Node deploys a chosen subset; no fixed global
module count is an availability contract.

| Module kind | Resource owner boundary |
| --- | --- |
| Files | Canonical paths/files in the selected Project workspace |
| Terminal | Project-bound process/jobs, home and workspace |
| Browser/Web | Project browser profiles/tabs and scoped network/file effects |
| SVC/provider modules | Explicit local repository/provider resource and connection binding |
| Infrastructure | Explicit approved infrastructure resource and operation |
| Reverse/Analysis | Project-bound native analysis state and controlled import/export |
| Other configured modules | Their registered typed action/resource owner contract |

Gateway admission and each module's exact effect check use the same
Node Access authority. Enforced mode requires current Cedar session grants;
auto-approved mode automatically approves valid sessions and their in-Project
actions. Both preserve Project isolation and session lifecycle. Catalog
presence/health is not an approval; see
[mode contract](../architecture/session-access-modes.md). Separate MCP endpoints retain their own protocol/catalog
and configured OAuth audience.

Node-local Projects share one logical Project UUID with Control Plane, but
Node UUID selects independent files/sessions/grants/resources. Effective
workspace/runtime isolation prevents sibling Project access.

Shared contract/runtime packages contain narrow reusable boundaries with
explicit consumers, never independent copies of policy or foreign ORM.

## Decomposition of runtime clients

`project_runtime_client` is not a target owner for module application logic.
Split by actual responsibility and consumers, not by historical extraction
wave or by moving the entire package into another universal shared folder.

| Existing responsibility | Target owner |
| --- | --- |
| Files read/write/upload/download orchestration, quota and transfer application scenarios | Files/Node application owner; module presentation adapts its typed contract |
| Terminal jobs, execution lifecycle and module-specific persistence | Terminal/Node application owner |
| Analysis native project/database/import workflows | Analysis module owner with private durable storage |
| Resource catalog/source management | Infrastructure Resources for shared sources; Node for materialized local values |
| Session requests, grants, admission and effect decisions | Node Access only |
| Descriptor-safe path/file primitives actually used by multiple modules | Focused filesystem capability, independent of human IAM and quota workflow |
| Cancellation-safe I/O or process primitives reused by multiple modules | Focused mechanism with explicit consumers; no duplicated session policy |
| Binary RPC/MCP framing, DTOs and generated service clients | Focused protocol/transport packages with owner-defined public contracts |

The current Web consumer uses some Files types and I/O mechanisms. Reuse
does not make the complete Files quota/signing/application stack a shared
owner. Separate the reused mechanism from the owner scenario before removing
that dependency. Do not move code into a module if it forces another module
to import its implementation directly.

Remove proven-unused historical implementations and obsolete compatibility
paths outright, including exclusive obsolete tests. Do not relocate dead
code or keep a fallback to satisfy an old test. Retain applicable invariants
and actual mechanisms, not historical module paths. First-party consumers,
dynamic registries, package inputs and Watch Paths must change together;
deployed data/artifacts require their own qualified retirement.

Follow [session access](../hands/node/session-access.md),
[Gateway](../services/gateway/node-management-and-mcp.md) and
[quality phases](../../scripts/quality/README.md).
