# Briareus — Infrastructure, Hands and focused Shared packages

**Status:** target source organization and ownership. Documentation does not establish a completed source move or accepted runtime deployment. Preserve service contracts, existing durable data, approved infrastructure scope and required quality checks during implementation.

## Source organization

Runtime source is grouped by responsibility under `infrastructure/` and
`hands/`. Reusable code lives in focused `shared/` packages. Project
documentation, quality tools and repository metadata have their own
non-runtime locations. Do not place application modules directly at root
or define a flat `services/` catalog as the target architecture.

- `infrastructure/` contains Control Plane UI/API, the panel ingress
  Gateway, backend identity integration, Platform, Resources and external infrastructure
  such as Rauthy, PostgreSQL and Valkey, grouped by responsibility.
- `hands/` contains the Node execution system, Node Gateway and MCP module
  runtimes. A Node deploys and manages several independently packaged MCP
  modules through their own Docker Compose definitions.
- `shared/` contains small, explicit reusable packages with narrow owners,
  stable APIs and identified infrastructure/Node/MCP consumers. Reuse is
  organized by actual capability or contract, not a broad common dump.

Each deployable module owns source, dependencies/lock, Dockerfile, Compose,
health/start and its own migrations where needed. Internal Clean
Architecture layers remain inside the owning module. Sharing a package
does not allow cross-service ORM, database or business ownership imports.

## MCP modules and local Projects

Every MCP module has one source directory under Hands, optional domain
grouping and its own Compose/Dockerfile/dependencies. Node deploys from
this catalog rather than copying source per Node instance. Each Node can
enable/disable a different set of module containers. Known, installed,
running and callable module states are distinct.

A Node hosts multiple isolated local Projects. Every session/grant and
execution resource has an exact Node/Project context. A logical Project
uses one Project UUID in Control Plane and on all attached Nodes. Registry
attachment records placement by Node UUID + Project UUID, without a separate
per-Node Project UUID translation. Workspaces, sessions, grants and runtime
state remain independent on each Node. Node has no human user/group/team
database or Rauthy requirement.

## Project identity and placement

Infrastructure is the human management plane: users, Teams/groups, human
scope, logical Project definitions and placement accounting. It orchestrates
Project creation on target Nodes through RPC. Node owns and persists each
actual local Project and its files/execution state; a logical Project may
exist on one Node and be absent on another.

The backend stores Node event projections for Node-wide and Project-wide
management views. Node-wide groups accessible requests by Node/Project/
session; Project-wide groups a logical Project's authorized placements.
Infrastructure filters and authorizes these human views before data is
returned. Project membership is not full Node management and Node selection
is not access to every hosted Project. No human IAM is copied into Node.

One logical Project keeps one Project UUID across Control Plane and its
Node placements. Local Project state means that Node's instance of this
identity, not a different local identifier. Node UUID + Project UUID selects
workspace, session-access state, resource bindings and execution context.

The same Project UUID on two Nodes does not share a filesystem, replicate
state or transfer session/approver authority. File transfer and resource
value delivery remain explicit operations targeted to the correct Node.
A UUID is a selector, not permission; names cannot silently merge Projects.

## Project workspace boundary

Private Project roots remain isolated. Node additionally exposes a separate
explicitly common persistent directory that all local Projects can read
and write without per-entry or individual operational-grant restrictions,
with session attribution and Node observation/audit. It never exposes private
Project roots, homes, profiles or native analysis databases and receives no
automatic copy of private files/credentials. It is not replicated across
Nodes. This shared-data namespace is distinct from system toolchains:
panel configures their tools/versions, Node installs them through consuming
image/Compose definitions, and workloads use the system installation
read-only. See [storage/tools](node-storage-and-transfer.md#node-wide-common-directory).

Each Node-local Project owns one persistent workspace shared by its Files,
Terminal, Browser and other MCP modules. Sessions use that workspace only
within their Project under the selected session-access mode; they do not own a duplicate
Project tree. Project workloads cannot directly inspect another Project's
workspace, terminal home, browser profile or runtime credentials. Enforce
actual filesystem/runtime isolation, not a common parent path plus a label.

Cross-Project file/directory movement uses the external transfer contract
with explicit target Node and target Project UUID and checks on both sides.
Target Node may equal source Node; this is still a transfer across Project
boundaries rather than an ordinary MCP path operation. Within a Project,
permitted subdirectory creation, copy/move and file work remain ordinary
workspace operations.

## Human identity and Node Access

Control Plane backend privately integrates Rauthy for human/MCP
identity, roles/groups and human management rights. In connected mode it
checks who may manage a Project or decide a requested access, then sends
an exact trusted management command to the relevant Node. Node validates
that authority rather than accepting role JSON or caller-selected claims.

Node Access is a logical component of Node runtime, not a mandatory new
microservice. It owns local Project-scoped AgentSessions, review metadata,
requests, audited grants/revocation and Cedar evaluation. Node Gateway
checks admission through Node Access; each MCP module checks the exact
effect through the same contract. It contains no human IAM implementation.

## Gateway deployment modes

Every Node includes a Gateway. If directly reachable, MCP clients connect
to that endpoint. Without public IP/reachability, the panel Gateway routes
the selected Node/Project to its internal Gateway over trusted transport.
Both paths reuse the same admission/effect contracts and enforcement.
Routing remains a Gateway function; Rauthy is an identity provider.

Standalone Node can start and manage local Projects and MCP modules
without the central panel, users, Teams or Rauthy. MCP OAuth may be absent
in explicitly configured standalone mode, while AgentSessions and Cedar
remain the local session model. Enforced mode requires explicit Cedar grants;
auto-approved mode automatically confirms valid sessions and their
in-Project actions. Project isolation is mandatory in either mode. Missing OAuth grants no management/approval
authority by itself. Connected authentication failure never silently enables
standalone mode or changes the policy. Human/operator control of standalone
management must remain separate from ordinary MCP operation admission.

## Session-access switch

The Node-owned enforced/auto-approved switch is independent of Panel
attachment and MCP OAuth. Auto-approved mode confirms all valid sessions
and every in-Project action without manual review or operational grants.
Only full trusted management changes mode. Session binding/lifecycle,
Project isolation, resource/command validity and audit remain mandatory.
No automatic decision grants full management or approver authority. Returning
to enforced mode requires explicit grants for new work; auto-approvals do not
become permanent grants. See [mode contract](session-access-modes.md).

## Separate MCP module endpoints

Clients connect separately to Files, Browser, Terminal and other MCP modules.
All module addresses terminate at Node Gateway; Gateway routes each to the
registered configured module deployment rather than merging their tools
into one aggregate MCP endpoint. Direct Node and panel-proxied ingress
preserve the selected Node/module endpoint and its protocol contract.

A module endpoint has its own MCP tool catalog and, when OAuth is enabled,
its registered resource/audience contract. Node instances may expose different
configured/ready module sets; a source catalog entry is not a runnable route.
Do not hard-code one global six-module set as available on every Node.

AgentSession is Node/Project-scoped, independent of an MCP transport
connection. A session can call its approved operations through several
module endpoints on the same Node, with admission under the selected
session-access mode and unconditional Project isolation each time.
Separate connections do not create implicit grants, a new real-world agent
identity or permission to use another Project/Node. Binary gRPC/WSS management
is a separate interface, not a replacement for each module's MCP protocol.

## Node management protocol

First-party control uses shared typed gRPC service/Protobuf contracts
through native gRPC or WSS/binary RPC adapters. Browser UI calls backend
over WSS; backend/internal services select the configured supported native
gRPC or WSS endpoint. Transport adaptation shares use cases, validation,
authority and typed errors/results. WSS is not native HTTP/2 gRPC. External
MCP retains its standard protocol and providers retain their native APIs;
no parallel REST/JSON management or GraphQL layer is selected.

Node and its Gateway form one managed runtime boundary. All external Node
management enters through that Gateway and reaches typed Node use cases;
the browser does not call the private management interface directly.
Node has a full management API but no human users/groups/roles. Ordinary
MCP session callers do not receive that unrestricted control interface.

Management supports both native gRPC and secure WebSocket (WSS) with binary
Protobuf messages. Both are required transports for the first iteration.
They use one versioned Protobuf command/result/event contract and the same
Node application use cases rather than REST/JSON CRUD endpoints. Native
gRPC uses HTTP/2; WSS carries binary Protobuf frames through an independent
adapter. WSS is not described as native gRPC or a separate business API.

Both adapters provide persistent bidirectional commands, results and events.
An operation has one correlation/idempotency identity across transports;
reconnect or changing transport must not execute the same command twice.
Share semantic validation, error/result mapping, Node/Project/session scope,
Cedar checks, audited outcomes and event ordering. Transport code owns only
framing, connection lifecycle and mapping to that application contract.
Protobuf parsing does not replace semantic input/authority validation.

The chosen deployment config identifies the transport and endpoint for each
connection. Both Core-initiated and Node-initiated orientations preserve the
same scenarios. Do not fall back to an anonymous/unrestricted channel when
a configured transport or its authentication requirements are unavailable.

Support explicit connection orientation: Briareus connects to a reachable
Node Gateway, or Node establishes an outbound channel to the control plane
when inbound reachability is unavailable. The command issuer and session
rights do not change with the connection initiator. Endpoint configuration,
registration/discovery and rollout are incremental; discovery alone does
not attach a Node to an arbitrary Project or grant a session access.

For MVP, the trusted private management channel need not implement its own
user login/OAuth or additional caller authentication. Its authority comes
from operator-controlled private connectivity and the infrastructure's
human scenario checks. It is a full control interface and is not available
to ordinary untrusted MCP workloads merely because they use the Gateway.
This does not expose anonymous public management or disable session/Cedar
checks on agent operations. Public connectivity and strengthened management
channel authentication are separate deployment capabilities.

Node emits pending-access notifications over this channel. The backend
updates the user's request queue/notifications; a human decision returns
over the same logical channel and Node applies it. Node does not contact
users, parse user roles or turn a notification into an approved grant.
Reconnection must preserve request/operation identity and avoid duplicate
approvals, container starts or other effects; retain exact Node/Project/
session scope and auditable outcomes.

Node is authoritative for all session requests, grants and checks. Backend
event projections are management read models only. Provide management RPC
for the full active-request set with bounded pagination, Node/Project/
session/status filters, exact lookup and revision/cursor reconciliation.
Manual refresh and reconnect recover missed events from Node state; stale
or disconnected projections are explicitly marked and confer no permission.
Node-initiated discovery and panel-initiated direct connections carry the
same commands/results/events. Discovery does not grant access or attach
Projects automatically; a Node without discovery remains independent.

## MVP human rights and session limits

Infrastructure validates the current authenticated user's Project/group
membership. In MVP, a user with access to a Project may perform all
management/approval operations within that Project. Per-action human
restrictions are deferred; the interface must not advertise them as an MVP
requirement. Project membership is not global ownership of every Project
hosted on the same Node.

Node applies only local Project/session authority. An approver session may
grant operational access only within its own Node and granted Project/
resource scope. It cannot manage another Node, call privileged control-plane
management, change human roles/groups or delegate approval authority.
Only a human/operator through the management interface appoints an approver
session. Cross-Node session approval/delegation is outside the first
iteration. Node full management and agent session approval are separate
interfaces, even when their transport terminates in the same Gateway.

## Shared packages and build watches

Extract functionality reused by infrastructure services or MCP modules
into a focused `shared/` package with known consumers. Prefer stable,
small public contracts and independently changeable capability packages.
Do not create an all-purpose package that imports unrelated functionality.
Keep real domain invariants with their owner rather than moving them into
shared merely to centralize code.

Each application's Watch Paths include its own module and only the shared
package paths it actually consumes. An unrelated shared package change must
not trigger that application's build or restart. Docker build inputs must
follow the same narrow dependency boundary; broad copy/import of all shared
code must not recreate global invalidation through the build context.
Documentation changes do not trigger runtime builds. Saved deployment
Watch Paths and actual rebuild behavior require independent verification.

Shared dependencies may form a transitive graph of focused packages;
declare direct dependencies and consumers so a changed package selects only
its actual deployable consumers. Multiple precise Watch Paths are expected.
Do not duplicate shared transport, Gateway or session-decision interfaces
per module to avoid a legitimate rebuild. MCP implementation changes update
only that module's affected containers; Node and unrelated modules continue
running. UI/backend changes do not restart databases or Nodes. An explicit
Node restart covers that Node's managed MCP set, preserving durable state.
See [deployment change matrix](../deployment.md#change-selection-and-restart-boundaries).

The existing approved Coolify External Services application is one vendor stack
with three separate private services: PostgreSQL, Valkey and upstream Rauthy.
Its source belongs to the external-infrastructure group under `infrastructure/`.
This is a deliberate infrastructure-only shared deployment unit, not permission
to package backend, UI, Gateway or Hands together. The existing
PostgreSQL and Valkey volume names and network must remain stable; Rauthy
uses its own logical database and a separate durable volume. The latest
owner instruction allows removing the unused legacy `deploy/data/**` source
during migration; do not delete data volumes or inspect plaintext secrets.

**Authentication:** `Control Plane UI → Control Plane backend → private Rauthy`.
Backend owns the private pinned provider protocol, sessions/challenges,
CSRF/PoW/MFA/OIDC state and protected administration credentials. Rauthy
verifies/stores human credentials and issues/revokes identity tokens; the
backend never implements a second password verifier or identity issuer.
All sign-in/MFA/recovery screens belong to UI. The resulting token returns
through backend RPC; provider cookies/keys remain server-side. No separate
infrastructure Authorization service exists. No provider-hosted login UI is
part of Briareus. Source configuration is not accepted deployment evidence.

## Shared resource delivery

Node supports locally owned resources and explicit Team-shared/external
source bindings. Required shared values are delivered and persisted in the
Node database before use, with source/binding/applied versions. MCP runtime
resolution is local; there is no per-action Control Plane fetch or Node
secret poller. Control Plane initiates source-change updates and periodic/
reconnect reconciliation over the same binary management channel. Node
applies scoped/versioned updates atomically and acknowledges without values.
Disconnected Node keeps its last applied state; remote changes apply after
delivery. Secret values and session-access grants remain independent. See
[resource delivery](resources-and-secret-sources.md).

## Node-owned storage

Each Node owns its filesystem/workspaces and all state needed for autonomous
execution: local Projects, AgentSessions, access requests/grants, revocation,
module/runtime records and its execution journal. Connected mode retains the
same ownership. The central Resources service is not the Node's runtime
storage owner, and a control-plane storage outage is not a reason to lose
local state or invent permission.

Application-facing persistence ports support SQLite and PostgreSQL adapters
with the same domain invariants. Select an adapter explicitly; do not change
backend or reset data automatically after a failure. A Node PostgreSQL
service/database belongs to that Node's managed runtime and storage contour,
not a dependency on central infrastructure. SQLite files and PostgreSQL data
must survive ordinary module/Node restarts and have scoped backup/migration.
Do not import ORM or persistence implementations across owners.

Optional Valkey/KV and computational scratch databases also belong to Node.
Ephemeral last-activity/cache state is distinct from durable grant decisions,
deadlines and revocation. Cache loss never creates an allow or extends a
hard access deadline. Keep operation identities, writer/replay invariants,
ordered event cursors and auditable outcomes consistent in both adapters.

Node-local files do not become a global mount shared by all Nodes. Provide
separate upload/download and cross-Node transfer ports through Node Gateway,
using the binary Protobuf/gRPC and WSS contracts. A transfer identifies source/destination Node, Project UUID and file/directory
resource; the destination may be another Project on the same Node. Each side checks its own
scope; files carry no session grant or approver authority to another Node.

Movement is a confirmed transfer followed by a separately authorized source
delete. Preserve the source if destination storage/integrity is unconfirmed.
Use typed operation identities/results so retries/reconnects do not duplicate
or silently overwrite unrelated files. Transfer is an explicit capability,
not automatic synchronization or a live workspace migration promise.

See [Node storage and transfer](node-storage-and-transfer.md).

Untrusted executors cannot access other Projects, private provider admin or
owner database credentials. A Node's container management privilege does not
belong to arbitrary MCP workloads. Preserve existing state and qualify live
migration/recovery/rollback separately; this specification authorizes no
reset, volume deletion, central data move or infrastructure deployment.

**Human first operator is a single *identity*, not a globally reused secret.**
Rauthy owns human groups, roles, administrator status and user access
rights. Platform references a verified provider issuer/subject and provider
user authority through the Control Plane backend; it has no separately assigned human
operator role. Cedar handles agent access approved by a participating user or a separate human-authorized approver session in a Project,
not human-role or group management. Email matching is not identity proof. Never reuse human/admin passwords for
PostgreSQL, Alembic, Valkey or private API keys. Rauthy v0.37.1 itself owns
empty-provider initial admin bootstrap; user-facing login, MFA and recovery
remain native Control Plane UI through its authenticated BFF. No password
is extracted from startup logs by other services.

## Execution and management contracts

```text
Direct MCP client ----> Node Gateway ---> MCP module
                            |                 |
Panel Gateway -------->     +--> Node Access <-+
                                (Project, AgentSession, Cedar)

Panel UI --RPC/WSS--> Control Plane backend ---> private Rauthy
                              |
                  shared RPC contract: native gRPC or WSS
                              v
                       Node Gateway ---> Node Access
                              ^
                    Node events / query results
```

Infrastructure supplies human collaboration and verified management
commands; Node supplies final session-operation decisions and enforcement.
Standalone Node does not fabricate central users, Teams or OAuth identities.
Automatic decisions identify their configured Node policy source, not a
fictitious human approver. Local Projects isolate execution resources.

Both standalone and connected deployments support both session-access modes.
Session metadata is untrusted; sessions inherit no grants from other sessions.
Only human/operator management appoints approver sessions, which cannot
appoint other approvers. Automatic approval grants no such authority.
In enforced mode explicit grants target session UUIDs with independent hard
deadlines; expiry blocks new work while admitted work finishes. Activity
refreshes only the idle clock in either mode. Automatic idle cleanup is
post-MVP.

## Deployment and build boundaries

Every deployable infrastructure, Node and MCP module has its own Compose
and build/dependency boundary. Deployment Base/Compose paths must resolve
to the actual selected module, with build context paths calculated from
its real location. Do not infer live paths from target documentation.

Watch the module's source and specific consumed shared packages. Verify
that an unrelated shared change causes no build/restart. Avoid a global
Compose lifecycle coupling the Panel and all MCP modules.
Node management of its own module Compose definitions does not imply
restarting every module whenever one changes.

Preserve the existing approved Development app UUIDs, routes, DNS aliases,
secret scopes and durable volumes during qualified cutover. No Production
change, broad redeployment, provider reset or data deletion is implied.

## Ownership and acceptance

- Backend owns Control Plane backend private Rauthy integration, human scope, management/event projections, Platform/Resources and their contracts. Frontend owns Control Plane UI. Runtime owns Hands Node, Gateway/Access, MCP modules and effect enforcement. Deployment owns approved external infrastructure and qualified path changes. Shared packages have explicit owners and consumers.

- Orchestrator updates agent tasks and checks folder ownership + handoff; no shared undirected source edits across lanes.
- Validate actual static/native build, required Git checks, scoped Coolify saved Base/Compose/Watch, real RPC/MCP consumer operations and independent restarts. Source/health is not accepted human authentication or Node session authority.
