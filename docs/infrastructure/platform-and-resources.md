# Platform and Resources — logical Projects and shared sources

**Platform** owns central Team/Project definitions, human membership/scope and Node placement/attachment records. The **Resources** owner holds Team-shared/external resource catalogs and source values. They do not become the runtime persistence store or access authority for every Node.

A logical Project has **one Project UUID** across Control Plane and every attached Node. Node UUID + Project UUID chooses its separate local state. A shared UUID is not shared filesystem, credential delivery, authority, replication or session/grant inheritance. Infrastructure validates human management scope before requesting a Node action; Node still enforces local operational effects.

Control Plane initiates delivery of shared resource values and reconciles source/binding/applied versions over the existing binary management channel. Node stores and resolves delivered values locally. Disconnected Nodes retain last applied state subject to actual provider validity; no per-MCP-call central secret fetch or automatic remote invalidation is promised. Secret values never appear in metadata/logs.

Details: [Project/Team model](../architecture/target-project-platform.md), [resource delivery](../architecture/resources-and-secret-sources.md), [binding RPC/delivery policy](../shared/rpc-and-delivery-policy.md), [Platform owner notes](../services/platform/README.md), and [Resources owner notes](../services/resources/README.md).
