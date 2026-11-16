# Hands — autonomous Node and MCP modules

Hands is the **execution plane**. Each Node includes its Gateway, Node Access/Cedar, local Project store/workspaces and a selectable set of independently packaged MCP modules. Infrastructure adds central human collaboration and management; it is not required for standalone Node execution.

| Responsibility | Owner documentation |
| --- | --- |
| Node, Gateway, access and session lifecycle | [Node overview](node/README.md), [binding access policy](node-access-policy.md), [session contract](node/session-access.md) |
| Project filesystem, shared directory, local state and transfer | [Binding storage policy](storage-policy.md), [storage contract](../architecture/node-storage-and-transfer.md) |
| MCP module layout and admission | [Modules](modules.md), [shared runtime capabilities](../shared/hand-runtime-capabilities.md) |
| Binary management and Node events | [Gateway management](../services/gateway/node-management-and-mcp.md), [shared RPC policy](../shared/rpc-and-delivery-policy.md) |

## Hand module families

The target provides **separate MCP endpoints**, not one aggregate toolbox. Each Node may install and enable a different subset; known, configured, installed, running, healthy and callable are different states.

- [Files](files/README.md), [Terminal](terminal/README.md), [Browser/Web](web/README.md)
- [Source-control provider SVC](svc/README.md), [Reverse/Analysis](reverse/README.md), [Infrastructure operations](infrastructure/README.md)
- Native provider sources may include radare2 and Serena under hands/; their source presence does **not** establish a configured or callable endpoint on any Node.

Module implementations and owner-local tests remain under hands/<module>/. Existing migration documents in each module directory describe ongoing consumer/source transitions and do not themselves authorize a live cutover. Do not reuse V1's combined Server Files/Terminal, single-node OIDC route catalog or Control Panel database as V2's Node-local execution architecture.
