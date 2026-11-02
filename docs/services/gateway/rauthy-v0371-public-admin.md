# Rauthy private management boundary

Rauthy administration is private to Control Plane backend through
the pinned provider API and scoped runtime credentials. Backend executes
typed human RPC scenarios; UI never receives provider operator keys,
direct password hashes, signing/encryption keys or an arbitrary admin proxy.

Rauthy owns users/credentials/MFA, groups/roles and token issuance. Briareus
does not implement a second identity store or reassign independent human
administrator roles. MVP infrastructure verifies Project/group membership
for that Project's management scenarios.

Gateway exposes only deliberately configured MCP/OAuth protocol routes,
not entire provider administrative namespaces or hosted login assets.
Human screens remain native Control Plane UI. Required route/method and
privilege classification follows the actual pinned provider source/config;
do not invent endpoints, successful permissions or static route safety.

Node management is a separate private gRPC/WSS interface. Node Access/Cedar
owns local Project/session grants and does not call Rauthy for agent access
requests. Standalone Node has no Rauthy/user/group/team requirement.

Validate real identity and privacy boundaries during separately authorized
acceptance. Source/health cannot establish login, user authority or protected
effect behavior. Preserve existing provider data, keys and approved app scope.

See [identity/access](../../architecture/identity-and-session-access.md) and
[Node management](node-management-and-mcp.md).
