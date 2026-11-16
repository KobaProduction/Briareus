# Shared contracts and reusable capabilities — V2

Shared packages contain **only reusable typed contracts, transports and narrow technical mechanisms** with known infrastructure, Node or module consumers. They are not another business owner, a global ORM/storage layer, or a universal policy engine.

| Responsibility | Documentation |
| --- | --- |
| Binary gRPC/WSS Protobuf and local resource delivery authority | [Binding RPC and delivery policy](rpc-and-delivery-policy.md), [Node management](../services/gateway/node-management-and-mcp.md) |
| Node Gateway/Hand admission and effect checking | [MCP runtime contracts](hand-runtime-capabilities.md) |
| Source package/domain boundaries | [Runtime module decomposition](runtime-module-boundaries.md), [Clean Architecture/DDD](../architecture/clean-architecture-ddd-briareus.md) |
| Narrow packaging, consumers, Watch Paths | [Consumer boundaries](consumers-and-watch-paths.md), [Deployment](../deployment.md) |

**Dependency direction:** domain → application ports (inward), outer persistence/provider/framework adapters implement those ports. Infrastructure and Hands own their domain invariants; shared modules may not depend on owner databases or implement user IAM or central Node/Cedar decisions. No ordinary untyped dictionary result contracts or duplicate policy implementations are introduced to evade migration.

The current checkout has shared/ packages but may still contain compatibility paths whose consumers require explicit validation before removal. A shared change selects only actual direct/transitive consumers; a broad shared/** Watch or COPY contradicts the target ownership contract.
