# V2 source ownership and cross-agent coordination

**Status: binding owner policy.**

**FOUR OWNERS / HANDOFF:** docs/operations/implementation-workflow.md.
**Coordination:** docs/operations/AGENT_COORDINATION.md is the tracked source. Local coordination/CONTRACTS.md, OWNERSHIP.md and requests/<lane>.md are optional handoffs only if explicitly supplied and present; do not fabricate missing files.
**Local task files:** Former agents/{backend,runtime,frontend,deployment}.task.md and coordination/ files are not tracked in this checkout. They are not mandatory prerequisites and must not be fabricated. Use the tracked coordination/implementation workflow documents and communicate in chat; inspect any explicitly supplied local handoff if present.
**BASELINE:** docs/architecture/engineering-requirements.md defines the service, storage, security and delivery requirements; docs/architecture/identity-and-session-access.md defines authentication and access ownership.

## Owners
Backend: Control Plane backend private Rauthy integration, human identity/management scope, RPC coordination and event projections; Platform/Resources owner scenarios. No central Node session/grant authority. Coordinate typed Node contracts with Runtime.
Runtime: Hands Node controller, isolated local Projects, Node Access sessions/grants/Cedar, Node Gateway and Compose-based MCP modules. Direct and panel-proxied ingress use the same Node contracts. No user/group/team or Rauthy subsystem inside Node.
Frontend: infrastructure Control Plane UI owns native sign-in/MFA/recovery screens, management and session-request review; it communicates through Control Plane API.
Deployment: infrastructure Rauthy/PostgreSQL/Valkey, approved runtime provisioning and provider contracts. Each module preserves its independent source/build/Compose lifecycle.

See [coordination](AGENT_COORDINATION.md), [implementation workflow](implementation-workflow.md), [quality phases](../../scripts/quality/README.md) and the explicit [Development allowlist](BRIAREUS_DEV_ACCESS_SCOPE.md).
