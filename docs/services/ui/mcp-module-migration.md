# Control Plane UI contracts

## Human identity

Provide native sign-in, MFA, recovery and current-user screens. UI calls
Control Plane backend RPC over WSS; backend owns private Rauthy integration.
No infrastructure Authorization service, hosted provider login navigation, direct provider API
calls, duplicate password verifier or fabricated identity/roles.

Present unavailable/unsupported protocol states honestly. Source config,
a successful health request or pending challenge does not authenticate a
person. API returns the intended provider-issued result; actual Project
access is verified separately. MVP Project members can manage all actions
in that Project; finer human per-action restrictions are later functionality.

## Project and Node management

Use one Project UUID across Control Plane/Nodes and show selected Node
placement separately. Workspaces/runtime/session grants are Node-local;
matching Project UUIDs do not imply synchronized files or global sessions.

Show Node attachment, module catalog/configured/deployed/running/callable
states and independent module/container operations from real owner data.
A catalog entry is not an enabled module or confirmed deployment. Clients
connect separately to module MCP endpoints through Node Gateway.

UI scenarios go through Control Plane API to the Node management contract.
UI does not call private full management directly, mount Node disk or
supply trusted approver status in ordinary JSON. Commands/results/events
use the shared gRPC/WSS contract behind API adaptation.

## Sessions and requests

Provide Node-wide and Project-wide management views through the backend.
Node-wide groups accessible requests by Node, Project and session;
Project-wide groups one logical Project's independent Node placements.
Both use infrastructure human-management scope and current Project access,
never a client-side filter over unauthorized rows. Show session UUID and
claimed agent/task metadata without asserting a verified agent identity.

The backend maintains event projections for these views. Display connection
status, last observed revision and stale/offline state honestly. Include
manual refresh that queries the owning Nodes' active-request RPC, with
pagination and filters, and reconciles the projection. A pending local UI
mutation is not a confirmed Node grant. Project absence on a Node is distinct
from an offline or not-yet-refreshed placement.

Show the actual Node session-access mode independently of attachment/OAuth.
In auto-approved mode valid sessions and all in-Project actions are confirmed
automatically; no pending review or human approval is invented. Project
isolation always applies. Mode changes use trusted full management, not
ordinary session hints; see
[mode contract](../../architecture/session-access-modes.md).

The review and explicit grant behavior below describes enforced mode.

Display recipient session UUID, Node/Project, claimed agent/type, task/
purpose, optional chat, requested actions/resources and per-grant deadline.
Metadata is review information, not verified agent identity. A caller may
create several independent sessions and new sessions inherit no grants.

Node pending events populate notifications/review. A human decision is sent
through the authorized management scenario and confirmed by Node state.
Only a human/operator appoints an approver session; that session can decide
operations only inside its Node/scope, never appoint others or cross Nodes.

Show session lifecycle separately from per-grant expiry. An expired browser
grant preserves the session and other access/new-request capability.
Activity affects only last-active/idle display, not hard grant deadlines.
Admitted work may finish after expiry; explicit cancel/stop is separate,
with its own verified privilege/result. Automatic idle cleanup is post-MVP.

Use exact current revisions and operation identities for mutations.
A timeout/ambiguous response is uncertain; reconcile with owner results/
events instead of inventing success or blindly issuing a new mutation.
Do not locally increment revisions or turn action hints into authority.

## Workspaces and resources

Present the selected Project root and its working subdirectories distinctly
from Node's intentionally common read/write directory. Show common usage/
state and attributed activity; do not imply that its contents are private
to one Project or apply per-entry grants. No private Project data is copied
there automatically. Native analysis stores remain private module data.

Provide Node system-tool management for adding/removing/configuring selected
tools/versions. Report desired configuration separately from observed installed
version, availability and failed installation. Node materializes it through
the consuming image/Compose lifecycle. Workloads use installed system tools
read-only while Project-local dependencies remain writable; common data is
not the system-tool installation. Full Node management is required to change
Node-wide tools; Project membership alone does not grant it.

Files, Terminal, Browser and other modules share only their Project workspace.
Do not expose sibling workspace paths, terminal homes, profiles or credentials.
Cross-Project/Node file/directory transfer explicitly selects target Node and
Project UUID, checks both endpoints and confirms destination before deletion.

Manage local resources and Team-shared bindings through owner scenarios.
Shared values are delivered into Node durable storage. Show reference/
version/application status; never token values in ordinary lists/logs.
Control Plane initiates synchronization; Node does not fetch per operation.

## Feature surfaces and acceptance

Present real owner contracts for Project/Team/Node management, session grants,
Files, Terminal jobs/logs/cancel, Browser controls and module resources.
Missing backend/runtime support is unavailable, not decorative enabled tools.

Keep FSD ownership/public APIs and typed transport/entity transformations.
Source/health/visual previews are not accepted product behavior. Follow
source-first work and separately user-authorized aggregate tests; publish
coherent locally validated batches. Preserve existing data and public
contracts through qualified changes.

See [API](../../control-plane-api.md),
[topology](../../architecture/infrastructure-hands-shared.md) and
[identity/access](../../architecture/identity-and-session-access.md).
