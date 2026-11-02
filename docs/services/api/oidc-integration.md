# Control Plane API owner adaptation

## Authentication boundary

Human authentication follows UI → Control Plane backend → private Rauthy.
UI owns native sign-in/MFA/recovery and calls backend RPC over WSS. Backend
owns provider session/challenge state and the pinned provider exchange;
Rauthy owns credentials/tokens/roles. There is no infrastructure Authorization
service, direct browser-to-provider call or duplicate identity signer/store.

Return the intended authentication result through that chain. Do not treat
an identity token, UI rendering or source configuration as Project access.
Infrastructure checks current Project/group membership; in MVP a member can
manage all actions in that Project. Human per-action restrictions are later.

## Project and Node scenarios

One logical Project has one UUID everywhere. Node UUID + Project UUID selects
its placement, local state and workspace. API validates the human scenario
and uses owner contracts; it does not open Node databases or mount global
workspace volumes. Membership in one Project is not global Node management.

Adapt Node operations to its Gateway management contract using native gRPC
or WSS/binary Protobuf. Both share use cases, validation, errors/results,
correlation/idempotency and event semantics. A connection may be initiated
by either side without changing who owns the management decision.

Node has no human user/group/team model. Trusted private full management is
separate from limited MCP session operations. Browser RPC methods/messages
are versioned together with UI; internal first-party services use native
gRPC or WSS adapters of their typed service contracts. Preserve published contracts
until a qualified change; this document does not invent deployed endpoints.

## Session review and events

Node owns enforced/auto-approved session-access configuration. Automatic
mode approves valid sessions and all in-Project actions without manual
grants or pending human review; Project isolation is unconditional. Only
trusted management changes mode. API/UI present the actual mode and
automatic decision source; see
[mode contract](../../architecture/session-access-modes.md).

The request-review behavior below describes enforced mode.

Node Access owns session creation, metadata, requests/grants, revisions,
audit/revocation and Cedar. Node emits pending events; API updates user
notifications/review and sends authorized decisions over the same channel.

Only human/operator management appoints an approver session. Local approver
sessions can grant operations within their Node/scope without UI participation;
they cannot appoint others, self-approve their requesting session, cross
Nodes or gain full Control Plane management.

List/review results distinguish session lifecycle from per-grant state.
Each grant has independent scope/deadline; expiry preserves other grants and
the session/request path. Activity never extends a grant. Work admitted
before expiry may finish; explicit stop/cancel is separate and requires its
own authority. Automatic idle shutdown/resource cleanup is post-MVP.

Mutation adapters preserve exact request/session/Node/Project identity and
current revision. Uncertain outcomes require reconciliation, not a blind
new request. Correlate results/events and refresh confirmed owner state;
UI hints and stale cached revisions are not permission.

## Files and resources

Project files use Node's shared-per-Project workspace with effective isolation.
API requests content/operations through Node contracts, not direct local disk.
Cross-Project/Node transfer specifies both endpoints and confirms destination
before separately authorized deletion. Data transfers no session authority.

Resources support Node-local values and explicit Team-shared bindings.
Shared values are delivered into Node durable storage for local operation.
Control Plane initiates updates and periodic/reconnect version reconciliation;
Node does not poll/fetch secrets per operation. Metadata/logs omit values.

## Errors and evidence

Distinguish invalid input, unavailable authentication/owner state, denied
authority, revision conflict and uncertain mutation outcome. Never fabricate
identity, an approved grant, successful effect or secret default.

Source contracts/health are not deployed acceptance. Follow source-first work,
separately authorized tests and locally validated batched publication with
data-preserving scoped rollout/rollback.

See [API responsibilities](../../control-plane-api.md),
[identity/access](../../architecture/identity-and-session-access.md),
[Node management](../gateway/node-management-and-mcp.md) and
[quality policy](../../../scripts/quality/README.md).
