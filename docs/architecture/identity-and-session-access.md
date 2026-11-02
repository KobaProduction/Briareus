# Identity and session access

## Infrastructure identity

Control Plane UI owns all human sign-in, MFA and recovery screens.
Authentication follows UI → Control Plane backend → private Rauthy.
The backend owns the version-pinned provider session/challenge/OIDC flow.
There is no separate infrastructure Authorization service. Rauthy stores and
verifies credentials/MFA and issues/refreshes/revokes identity tokens.
The intended authentication result returns through that same chain.
Browsers do not open Rauthy login pages or call it directly.

Keep provider cookies, CSRF/PoW state, PKCE/state/nonce and operator keys
inside the Control Plane backend. Do not persist/log passwords in UI,
API or Node, duplicate the identity signer or invent password-to-token
shortcuts. Unsupported/missing provider continuations fail without a
fabricated identity or fallback login provider.

Rauthy creates its initial administrator during empty-provider initialization.
The operator signs in through Control Plane. No startup registration link,
first-visitor administrator assignment or repeated provider bootstrap is
triggered by missing local user projections. Preserve existing accounts,
keys/state and qualify any actual cutover.

Rauthy is authoritative for human users/groups/roles/administrative status.
Platform stores domain objects and stable identity references, not independent
human role assignments. Match the verified issuer/subject, not a supplied
email or role JSON. In MVP infrastructure checks current Project/group
membership; an authenticated member can manage all actions within that
Project. Per-action human restrictions are deferred.

## RPC and Node authority

All first-party control communication uses one typed gRPC service/Protobuf
contract with native gRPC and WSS binary RPC transport adapters. Browser UI
calls backend RPC over WSS; internal services and backend/Node use native
gRPC or WSS according to endpoint capability and explicit configuration.
WSS is an adapter for the same service methods, not native HTTP/2 gRPC.
Share application semantics, validation, errors, revisions and operation
identity across adapters. No separate REST/JSON management implementation
or GraphQL layer is selected. External MCP keeps its standard protocol;
private Rauthy and other providers retain their supported native protocols.

Node includes Gateway and Node Access, which owns local Project session
requests/grants, audit/revocation and embedded Cedar decisions. It contains
no human user/group/team database or Rauthy requirement. Infrastructure
checks human scenarios and forwards management decisions; Node applies
them without implementing human IAM.

Control Plane backend checks current human Node-management scope and
Project access, orchestrates Node commands and maintains event projections.
Node-wide views group accessible Node/Project/session requests; Project-wide
views aggregate accessible placements of a logical Project. Queries and
decisions are filtered before returning data, not merely hidden in UI.
Node owns requests/decisions durably. Active-request RPC with pagination,
scope/status filters, exact lookup and revision/cursor reconciliation
supports manual refresh and reconnect; projections confer no authority.

Native gRPC and WSS/binary Protobuf management adapters share one contract,
validation and application use cases. Persistent bidirectional channels
carry commands/results/events in either connection orientation. Node signals
pending requests; Control Plane notifies users and sends decisions back.

Trusted private MVP management needs no separate user/OAuth or additional
caller-login layer. It is full control and is separate from ordinary MCP
workloads and limited session APIs. Human/operator control can appoint an
approver session; a session cannot invoke unrestricted management merely
because it reaches the Gateway.

Node can start and operate its Projects, modules, sessions and local storage
without Control Plane or any infrastructure service. Standalone mode can
omit MCP OAuth while retaining local Projects/sessions and Node Access. Connected-mode identity failure never silently enables standalone
mode. Node's durable state and approved local grants do not require a
synchronous central permission/storage call for every effect.

## Project identity and isolation

One logical Project has the same Project UUID in Control Plane and every
Node placement. Node UUID + Project UUID selects independent local workspace,
session/grant state, resource values and execution. No local-ID translation,
shared filesystem, grant inheritance or automatic replication is implied.

Each Project workspace is shared by its Files, Terminal, Browser and other
modules. Runtime/filesystem boundaries isolate sibling workspaces, homes,
browser profiles and credentials. Paths, symlinks and metadata cannot switch
Project. External transfer identifies both Node/Project endpoints, even on
the same Node, and never carries session authority.

## MCP connections and sessions

The separately configured Node-wide common directory is intentionally
readable/writable by all local Projects, with observation/audit and no
per-entry or individual operational-grant restrictions. It is outside
Project-private roots and is not another Project's private data. No private
files, credentials or module state are automatically published there.
System toolchains are separately Node-managed and read-only to workloads;
see [storage contract](node-storage-and-transfer.md#node-wide-common-directory).

Files, Browser, Terminal and other modules have separate MCP endpoints
through Node Gateway; no all-tool aggregate endpoint is implied. Direct
and panel-proxied ingress preserve the selected Node/module. Each module
keeps its own catalog/protocol and configured OAuth resource/audience.
Available module sets differ by actual Node deployment/readiness.

AgentSession is a Node/Project access principal, independent of a transport
connection or persistent real-world agent identity. One client can create
many independent sessions. A session may use approved operations through
several module endpoints on the same Node; every effect needs its applicable
access according to the selected Node mode. In enforced mode a new
connection/session grants no operational access by itself.

Authenticated or explicitly standalone-mode callers use lifecycle tools
to create a session before protected work. No pre-existing AgentSession is
required to create one; in enforced mode creation grants no protected effect.
In auto-approved mode valid creation returns a ready session and every
in-Project action is automatically approved without manual review. Missing session
returns a structured session-required result. Session UUID selects state;
its mere presence and caller metadata do not create authority.

MVP metadata describes claimed agent name/type, purpose/task and optional
chat reference. It supports review but proves neither unique agent identity
nor chat ownership. Matching metadata cannot transfer grants. Audit records
identify actual session UUIDs and decisions rather than claiming different
sessions prove different real-world agents.

## Session-access mode

Node has an explicit enforced/auto-approved switch independent of whether
it is attached to Control Plane. Auto-approved mode automatically confirms
all valid sessions and their actions inside their Project. It bypasses
manual operational grant/Cedar approval requirements, not Project isolation,
session identity/lifecycle, protocol validation or infrastructure human IAM.
Only full trusted management changes the mode. Switching back requires
explicit grants for new work; automatic approvals create no permanent grants
or approver authority. See [mode contract](session-access-modes.md).

## Requests, grants and approver sessions (enforced mode)

Requests go to Node Access/Cedar, never Rauthy. Record recipient session,
Node/Project, requested actions/resources and lifetime with review metadata.
A Project member may decide through Control Plane; a separately authorized
approver session may decide through the restricted local session API.

Only a human/operator through full management grants approval authority to
a specific session and Node/Project/resource scope. An approver session can
grant operational access, such as Browser use, but cannot appoint another
approver, delegate approval authority, approve its own requesting session,
manage another Node or gain privileged Control Plane/human-role access.
Enforce this for direct APIs and indirect grant/policy mutations.

Both decision paths reach the same Node application use cases, Cedar checks,
idempotent durable decisions and audit. Bind approval to exact request/scope,
recipient and current revision. Unknown resources, wrong Project/Node,
insufficient scope or unverifiable required state deny new protected work.
Node Gateway coarse admission is not blanket permission for module effects;
the module resolves the canonical resource and checks that exact operation.

## Explicit grant deadlines, activity and work in progress

Each grant has its own finite deadline or explicit non-expiring mode and
remains revocable. A five-minute grant cannot be extended by its holder,
activity or keepalive. A separate authorized, audited management/approval
decision may change its deadline; no silent scope or approval-authority
expansion follows.

In enforced mode, expiry disables only that grant. The session, other valid grants and new
request capability remain. Check the applicable grant when admitting new
work. An operation admitted and started before expiry may finish after it;
passive deadline expiry does not cancel it. Later operations require current
access. Explicit revoke/cancel/session-stop are separate commands.

Accepted actions refresh a separate sliding last-activity/idle record in
Node-local Valkey/KV. They do not change durable grants/deadlines, revive a
stopped session or extend OAuth/peer-proof validity. Cache loss never creates
an allow. Automatic inactivity-triggered shutdown/resource garbage collection
is post-MVP. Explicit stop requires its applicable user/session privilege;
approval authority alone is not an implicit stop privilege.

Project files and resources shared by other sessions are not owned by a
session merely because it used them. Session resource cleanup must preserve
Project data and unrelated active work.

## Data and delivered resources

Node owns durable Projects/sessions/grants, revocation and execution journal
behind SQLite/PostgreSQL ports, plus its files and optional local KV/scratch
stores. No central Resources runtime journal is required.

Team-shared resource values are delivered into Node storage with binding/
source/applied versions. MCP runtime resolves them locally. Control Plane
initiates source updates and periodic/reconnect reconciliation; Node does
not poll/fetch secrets per action. Disconnected Node retains last applied
state subject to actual provider validity. Remote changes apply after
delivery, not instantaneously while disconnected. Secret versions and
session grants are distinct authority.

## Acceptance

Finish source owners before separately user-authorized testing. Verify real
human login/challenges/tokens, Project membership, both management transports,
both session-access modes and unconditional Project isolation,
Node-local request/approve/deny/revoke, session/grant lifecycles, exact module
effects and filesystem isolation. Source, health and fixtures do not prove
deployed acceptance. Preserve data and approved rollout/rollback boundaries.

See [topology](infrastructure-hands-shared.md),
[storage/transfer](node-storage-and-transfer.md),
[resource delivery](resources-and-secret-sources.md) and
[quality policy](../../scripts/quality/README.md).
