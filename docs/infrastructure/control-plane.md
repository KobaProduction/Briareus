# Control Plane — UI, backend and human management

**Owners:** Frontend manages native sign-in/MFA/recovery and human workflows. Backend privately integrates the version-pinned Rauthy protocol, validates human Project membership and Node-management scope, coordinates typed commands, and maintains read projections of Node events.

Authentication follows **Control Plane UI → Control Plane backend → private Rauthy**. Rauthy alone stores/verifies credentials and issues tokens; provider admin keys and challenge state remain server-side. Do not implement an independent human identity verifier, redirect all sign-in to a hosted Rauthy UI or expose arbitrary provider admin routes.

Browser UI uses **WSS binary Protobuf RPC** to the backend. Internal first-party control uses versioned gRPC service/Protobuf contracts with native gRPC and WSS adapters of the same application use cases; external MCP/provider-native protocols are separate. WSS is not native gRPC/HTTP2. Existing HTTP routes are migration consumers and cannot be deleted merely because the target contract selects RPC.

The backend may display Node-wide and logical-Project-wide sessions/requests using event projections. A projection is not Node authority; disconnects mark it stale. Manual refresh/reconnect must query authoritative Node active-request state with pagination and revision/cursor reconciliation. A human Project member can manage that Project under the selected MVP rights, not other Projects or all Node host resources.

Details: [binding policy](identity-and-human-authority.md), [Control Plane RPC](../control-plane-api.md), [identity/session access](../architecture/identity-and-session-access.md), [UI](../services/ui/mcp-module-migration.md) and [backend provider integration](../services/api/oidc-integration.md).
