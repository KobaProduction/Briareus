# Briareus V2 — system architecture

This is the entrypoint for the **target V2 architecture**, not proof of a completed source migration or a live deployment.

## Reading order

1. [Engineering requirements](../architecture/engineering-requirements.md) and [architecture overview](../architecture/overview.md).
2. [Owner topology and source boundaries](../architecture/infrastructure-hands-shared.md).
3. [Binding source/repository policy](source-topology-policy.md).
4. [Infrastructure](../infrastructure/README.md), [Hands and autonomous Node](../hands/README.md), and [focused Shared](../shared/README.md).
5. [Operations](../operations/README.md), quality/acceptance and deployment restrictions.

A logical Project uses one UUID across Control Plane and its Node placements, but each Node's workspace, sessions, resources and state are **local**. Human authority belongs to Infrastructure/Rauthy; operational session access belongs to Node Access/Cedar. Direct and panel-proxied MCP ingress use the same Node decisions.

**Implementation boundary:** the target groups runtime source under infrastructure/ and hands/ with focused shared/ packages. In the current V2 checkout, code still exists under services/ and hands/, and the infrastructure/ source root has not yet been populated. Do not treat source diagrams as proof of file moves or approved Coolify Base/Compose/Watch settings.

V1 is a separate maintained version and must not be used as the source of V2 Node/session authority.
