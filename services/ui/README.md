# Briareus Control Plane UI

The Vue/TypeScript/Bun UI is an infrastructure component with its own
dependency lock, build/Compose and actual shared consumers. It owns
presentation and user workflows, not identity storage, Node grants or a
global workspace filesystem.

## Human and Project scenarios

Provide native sign-in/MFA/recovery through UI → backend RPC/WSS →
private Rauthy. Backend owns the provider protocol; no separate infrastructure
Authorization service exists. No direct browser provider calls, hosted login
navigation, browser password persistence or fabricated user/role success.
Return intended authentication results through that chain; verify actual
Project access separately. MVP members may manage all actions in that Project.

Use the common logical Project UUID and select Node placement independently.
Matching Project IDs across Nodes do not share files, sessions or grants.
UI calls typed versioned Control Plane API contracts, not Node private full
management or raw owner databases.

## Module and session interfaces

Show actual Node/module configured/deployed/running/callable states. Clients
use separate MCP module endpoints through Node Gateway, not a merged all-tool
server. Catalog presence or a healthy process is not an enabled effect.

Show the actual Node enforced/auto-approved mode independently of attachment
and OAuth. Automatic mode confirms valid sessions and all their in-Project
actions without pending human review; Project isolation always applies.
Use trusted management for mode changes and display automatic decisions
honestly; see [mode contract](../../docs/architecture/session-access-modes.md).

In enforced mode session review displays UUID, Node/Project, unverified agent/task/optional chat,
requested actions/resources and each grant's scope/deadline. Node emits
pending events; authorized decisions return through management and are
confirmed by Node state. Only human/operator management appoints approver
sessions, which remain Node/scope-local and cannot appoint others.

Expiry of one grant preserves the session/other grants and lets admitted
work finish. Activity changes idle state only. Explicit cancel/stop is
separate with its own authority; automatic idle cleanup is post-MVP.
Never turn stale UI action hints into permission or invent owner revisions.

## Files, resources and errors

Modules share only their Project workspace. External transfer explicitly
selects target Node/Project and checks both endpoints, including same-Node
cross-Project movement. UI never exposes sibling host paths or secret values.

Shared resource values are delivered into Node durable storage; Control
Plane initiates updates and periodic/reconnect version reconciliation.
Display reference/version/status, not token material.

A command timeout is uncertain, not automatic failure or success. Reconcile
exact operation identity/current owner state instead of blindly issuing a
new mutation. Unavailable owner/protocol/script state remains unavailable;
it never opens a guest/provider-login or permission fallback.

## Architecture and delivery

Retain FSD layers, entity models, public slice APIs and typed transport.
Keep business orchestration out of components and domain logic out of
generic shared UI. Watch/build only actual module/shared inputs.

Finish all source owners before separately authorized tests/fixtures.
Validate coherent batches locally with runtime/lint/type/test/hook checks
before ordinary scoped publication. Preserve public contracts, data and
qualified rollout/rollback. Source/health/visual previews are not accepted
login or protected-operation behavior.

See [UI contracts](../../docs/services/ui/mcp-module-migration.md),
[Control Plane API](../../docs/control-plane-api.md) and
[quality policy](../../scripts/quality/README.md).
