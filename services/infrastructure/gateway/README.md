# Gateway implementation boundary

Gateway transport serves its configured infrastructure or Node role without
owning human IAM, Project business objects or duplicated policy.
Node always includes Gateway and Node Access/Cedar; separate module MCP
endpoints route to actual configured/ready deployments.

Preserve streaming/body/query/status and legitimate end-to-end metadata.
Do not fabricate identity/permission from caller headers or publish private
management/provider routes through a generic forwarding fallback.
Full private Node control is distinct from limited MCP session calls.

Source paths and health do not establish current deployment settings.
See [Gateway contract](../../../docs/services/gateway/node-management-and-mcp.md)
and [topology](../../../docs/architecture/infrastructure-hands-shared.md).
