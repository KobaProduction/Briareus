# Node Access: session request and decision contracts

## Owner and callers

Node Access is a component of Node runtime. It owns Project-scoped session
requests/grants, approver authority, audit/revocation and embedded Cedar.
Infrastructure owns human identity and human management scope, not the
Node's execution database or per-effect policy store. No infrastructure
Authorization service participates in Node session admission or decisions.

Node Gateway requests coarse session/tool admission. Each MCP module
resolves the actual canonical Project resource and requests an exact effect
decision through the same Node Access application contract. A coarse Permit
does not authorize arbitrary resources. Adapters do not copy policy logic.

Standalone Node may omit MCP OAuth in explicit mode while keeping sessions
and Cedar. Connected mode enforces configured identity/audience requirements;
unavailable identity never silently selects standalone. Full private
management and limited MCP session methods remain separate.

## Session lifecycle

Lifecycle creation is available without a pre-existing AgentSession and
in enforced mode grants no protected operation. In auto-approved mode,
valid creation automatically returns a ready session with in-Project action
approval. Record UUID, Node UUID, logical Project UUID,
untrusted agent/purpose/optional chat metadata and lifecycle/revision.
A caller can create multiple independent sessions; metadata matching cannot
transfer authority. Node UUID + Project UUID selects local state.

Grants target the recipient session, exact actions/resources and independent
deadline or explicit non-expiring mode. Store requests/decisions/current
revisions durably through Node SQLite/PostgreSQL ports. KV activity/cache
is separate from durable approval authority.

## Session-access modes

Node Access owns the explicit enforced/auto-approved switch, independently
of Panel attachment or transport OAuth. Auto-approved mode approves every
valid active session and its in-Project actions without waiting for a human
or approver session and without requiring a manual Cedar grant. Keep session
binding/lifecycle, Project isolation, command/resource validity and audit.
Only full management changes mode; it never gives an MCP caller management
or approver authority. Returning to enforced mode requires explicit grants
for new work; automatic decisions do not persist as permanent grants. See
[mode contract](../../architecture/session-access-modes.md).

## Approval and revocation (enforced mode)

Requests go to Node Access, never Rauthy. Emit a pending event over the
management channel. Infrastructure checks human Project access, notifies
the user and returns the authorized decision; MVP Project members can
manage that Project fully.

Human/operator management may appoint an approver session for an exact
Node/Project/scope. It may decide operational requests through a restricted
session method without waiting for a person. It cannot appoint approvers,
delegate that authority, self-approve the requesting session, cross Nodes
or gain unrestricted upstream management.

Both paths call the same Node application use cases, validate current
authority/request/revision and persist idempotent audited outcomes.
A claimed UUID, role header, tool catalog or human token alone grants none.
Audit actual session identifiers, not an inferred unique agent identity.

## Exact operation decisions

The deliberately Node-wide common directory is a separate canonical
shared resource. All local Projects have read/write access without individual
operational grants or per-entry restrictions in either session-access mode.
Node still binds the action to the active session/Node for observation/audit
and validates paths so this resource cannot select private Project or
module storage. Private Project effect decisions below use the selected
mode. System tool installation is separate read-only state managed by Node.

Inputs identify the local Node/Project/session, action, canonical resource,
expected revision and operation identity. Values are typed selectors;
trusted state comes from owner/session/runtime contracts. Reject unknown
actions/resources, wrong Project/Node, unavailable required state and
in enforced mode insufficient grants. Return a typed Permit/Deny/unavailable result; do not
invent a bearer or a successful effect from a decision.

Bind admission to the exact operation/resource. Verify provider identity
when configured. In enforced mode verify the current applicable grant
before new protected work; in auto-approved mode record the automatic
policy decision without requiring that grant.
Do not use another grant's later expiry or a cached old revision to allow it.

Each module retains its own MCP endpoint/catalog and configured audience.
A session can use multiple same-Node endpoints only within its scope.
Gateway does not interpret business arguments to invent a resource binding.

## Explicit grants, time and execution

Explicit grant deadlines are hard limits. Activity/keepalive changes only
local idle state, never access duration. Deadline changes require a separate
authorized decision. In enforced mode expiry disables only that grant; session, other grants
and new-request capability survive. Work admitted and started before expiry
may finish; expiry alone does not cancel it. New operations need current access.

Explicit revoke/cancel/session-stop is separate. Session cleanup cannot erase
shared Project files or unrelated work merely because a session used them.
Automatic inactivity shutdown/resource collection is post-MVP. Stop privilege
is separately checked, not implied by approval authority.

## Transport and state

Requests originate and persist inside Node. The panel receives events and
maintains a management read projection, not a duplicate authority store.
Provide management queries for the complete active-request set with bounded
pagination and exact Node/Project/session/status filters, exact request
lookup and revision/cursor reconciliation. Manual refresh and reconnect
must recover authoritative state after missed events. Human Node-wide and
Project-wide visibility is checked in infrastructure; Node stores no
corresponding users, groups, Teams or owners.

Full management supports native gRPC and WSS/binary Protobuf with one schema,
use cases and validations. Preserve operation identity across reconnect/
transport changes, ordered events, exact scope and idempotent outcomes.
Node state does not require a central Resources journal.

Node emits versioned status/results without leaking credentials or secret
values. Team resource delivery is a distinct Control Plane-initiated update;
secret versions never imply session permission.

## Acceptance

Follow the separate source/test phases. Qualified behavior includes session
creation/readiness in both modes, metadata, no inheritance, Project isolation,
human/local approver decisions, exact
effect Permit/Deny, expiry, revocation and storage/restart consistency.
Source, health and fixtures alone are not deployed acceptance. Preserve
existing data and current rollout/rollback scope.

See [identity/access](../../architecture/identity-and-session-access.md),
[topology](../../architecture/infrastructure-hands-shared.md) and
[quality policy](../../../scripts/quality/README.md).
