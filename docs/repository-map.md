# Repository organization

Runtime roots are grouped by responsibility:

```text
infrastructure/   control plane UI/backend, panel Gateway, human management,
                  Platform/Resources and external dependencies
hands/            Node/Gateway/Access and grouped MCP module catalog
shared/           focused contracts, transport and reusable capabilities
docs/             architecture and engineering/runtime requirements
scripts/          tooling and quality enforcement
```

Node includes Gateway. Each MCP module has one catalog directory with its
Compose, Dockerfile, dependencies/lock and health/start contract. Nodes
select subsets without source copies per instance. Catalog presence is not
deployment or callable readiness.

Each deployable module retains its own build/Compose lifecycle. Internal
architecture layers stay inside the owner. Shared packages have narrow APIs
and explicit consumers, never owner ORM or cross-service business authority.

Watch/build inputs cover the module and only consumed shared packages.
No flat service catalog, runtime modules directly at root or blanket shared
watch is the target. Documentation does not trigger runtime builds.

This organization does not claim checkout paths or saved Dev settings
already match. Qualify source/deployment moves while preserving existing
state, contracts and rollback. See
[topology](architecture/infrastructure-hands-shared.md).
