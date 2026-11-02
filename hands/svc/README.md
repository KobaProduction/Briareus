# SVC/provider MCP module

SVC provides its registered provider/repository operations through a separate
MCP endpoint routed by Node Gateway. It owns module packaging and configured
connections; Node Access/Cedar owns session operation/resource grants.

Credentials resolve locally on Node, including delivered Team-shared resource
values. Control Plane initiates updates/reconciliation; no per-operation
central secret fetch or duplicate human IAM is required.

Configured identity requirements apply; explicit standalone mode may omit
OAuth while retaining sessions/Cedar. Catalog/health does not establish
callable effects. Preserve provider schemas, Project isolation, data and
qualified rollout. Watch only module source and actual shared consumers.

See [module contract](../../docs/hands/svc/README.md) and
[resources](../../docs/architecture/resources-and-secret-sources.md).
