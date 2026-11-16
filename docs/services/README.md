# Existing service documentation — Infrastructure migration sources

These pages describe **service owner contracts and ongoing migration evidence**. The target V2 Infrastructure owner index is [here](../infrastructure/README.md). A directory under docs/services/ is not proof that runtime source has moved to the target infrastructure/ directory or that Coolify Base paths have changed.

| Existing owner | Documentation |
| --- | --- |
| Control Plane backend, Rauthy identity flows | [Native sign-in](api/native-login.md), [private provider integration](api/oidc-integration.md), [resource intent](api/oidc-resource-intent.md) |
| Control Plane UI | [UI migration](ui/mcp-module-migration.md) |
| Gateway and management transport | [Node RPC/Gateway](gateway/node-management-and-mcp.md), [runtime admission](gateway/runtime-admission.md) |
| Vendor infrastructure | [External Services](external/README.md) |
| Human Team/Project ownership | [Platform](platform/README.md) |
| Shared sources and bindings | [Resources](resources/README.md) |
| Retired owner | [Old infrastructure Authorization](authorization/service-folder.md) — protected migration inventory only |

**Current target:** Infrastructure holds human users/Teams/Project management and private Rauthy integration. Hands/Node Access alone owns local session approvals/Cedar. UI/browser control uses WSS/Protobuf, backend/internal management uses the supported native gRPC or WSS adapters. Do not expose provider administrative APIs as browser or agent tools.

See [binding identity policy](../infrastructure/identity-and-human-authority.md), [Hands](../hands/README.md), and [approved Development scope](../operations/BRIAREUS_DEV_ACCESS_SCOPE.md).
