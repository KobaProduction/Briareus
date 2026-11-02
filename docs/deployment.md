# Development deployment requirements

Runtime source is grouped under infrastructure/ and hands/, with focused
shared packages. Each deployable module owns its build, Compose, dependencies
and lifecycle. Nodes select different MCP module sets without source copies.

Watch/build inputs cover the owning module and actual shared consumers,
not every shared/external directory. Docs-only changes do not trigger runtime
builds. Verify saved Base/Compose/Watch independently; a target path is not
proof of the current deployment setting.

## Change selection and restart boundaries

Watch Paths follow the transitive dependency graph of the changed source.
Several precise paths per application are expected; path count is not a
reason to watch an entire shared or external-services tree. A package lists
its direct consumers and shared-package dependencies. A change reaches
only those deployable consumers that depend on it, directly or transitively.
Shared transport, session-decision contracts and Gateway plumbing have one
implementation in focused packages; module-specific provider logic stays
with its MCP module. Do not copy shared code into each module to narrow watches.

| Changed input | Deployment/restart boundary |
| --- | --- |
| Control Plane UI | UI only |
| Control Plane backend implementation | Backend only; no automatic database, UI, Node or MCP restart |
| External database/provider configuration | Its owning external deployment; no blanket application watch |
| Node runtime | The affected Node and its managed MCP container set during an explicit Node restart |
| One MCP implementation | Only that module's affected containers on Nodes where it is deployed; Node and unrelated modules keep running |
| Focused shared package | Actual direct/transitive consumers, each through its own lifecycle |
| Documentation | No runtime build or restart |

Coolify selects affected applications from a coherent push through native
Watch Paths. Node records and manages a changed MCP release through its
module/container lifecycle; a module update is not a Node restart. A Node
restart may restart its managed module set, preserving Project data and
module-owned persistent storage. Container build/management privileges
belong to Node/operator management, never ordinary MCP workloads.

Saved Coolify settings, Compose watch declarations and the dependency graph
must agree before rollout. Existing broad watches are migration defects,
not an instruction to reproduce them. This document does not update saved
settings or authorize a running deployment change.

Node system-tool selection is panel-managed configuration, applied by Node
through the default image/Compose inputs of its actual consuming containers.
Tool additions/removals/version changes replace only those consumers and
preserve Project roots, common data and native analysis stores. System
installations are read-only to workloads; the separate Node-wide common
directory is intentionally writable by all local Projects with observation/
audit. Neither a tool update nor an MCP update implies a full Node restart.

The deployment reference is
[AI Agent Workflow / Service Engineering](https://github.com/ArthurKoba/ai-agent-workflow/blob/main/skills/service-engineering/README.md)
and its
[Coolify contract](https://github.com/ArthurKoba/ai-agent-workflow/blob/main/skills/service-engineering/coolify-compose.md).
Project-specific ownership, existing application identities and approved
scope remain binding; those generic examples are not live inventory.

Finish all source owners before separately user-authorized testing.
Work mainly locally, then publish coherent owned batches after affected
runtime/lint/type/test/hook validation of the exact outgoing revision.
No approval per ordinary push/approved Dev rollout is required. Avoid tiny
pushes, repeated identical CI and unverified peer source; preserve protections.

Use only the exact [approved Development scope](operations/BRIAREUS_DEV_ACCESS_SCOPE.md).
Do not view unrelated resources or plaintext secrets. No Production, new
application identity, source layout or feature document authorizes a live
reset, data move or global restart.

Infrastructure owns human/Rauthy and central registry state; each Node owns
its files, session/grant state, execution journal and selected SQLite/PostgreSQL
backend. Preserve existing databases, volumes, keys, provider accounts and
workspace content until a qualified migration with recovery/rollback.

Qualify both native gRPC and WSS/binary Protobuf management, required connection
orientations, direct/proxied per-module MCP ingress and actual Project
workspace isolation. Health, source interfaces and image success alone do not
establish human login, session grants or effect acceptance.

See [topology](architecture/infrastructure-hands-shared.md),
[workflow](operations/implementation-workflow.md) and
[quality policy](../scripts/quality/README.md).
