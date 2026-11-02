# Briareus engineering requirements

## Architecture and ownership

Runtime code is grouped under infrastructure/ and hands/. Focused shared
packages have stable APIs, explicit owners/consumers and narrow watches.
Each deployable module owns source, dependencies/lock, Dockerfile, Compose,
health/start and its own migrations. Documentation stays outside runtime
build/watch inputs.

Infrastructure provides Control Plane UI/API, private Rauthy integration,
human/Team collaboration and central Project/Node registration. Node owns
Gateway, local Project placements, Node Access/Cedar, sessions/grants,
MCP module/container lifecycle, filesystem and durable execution state.
No human users/groups/Teams or Rauthy live inside Node. A Node can start,
manage local Projects/modules and execute work without the Panel or any
external infrastructure service; its own configured storage belongs to Node.

Each MCP module has one catalog directory and its own Compose. Nodes may
deploy different subsets. Clients connect to separate module MCP endpoints
through Node Gateway, directly or through Control Plane ingress; tools are
not merged into one aggregate endpoint.

## Identity and session authority

Human sign-in/MFA/recovery uses native Control Plane UI → backend →
private Rauthy. Backend owns provider sessions/challenges and private
integration; no infrastructure Authorization service exists. Rauthy owns credentials/tokens/groups/
roles and creates the initial administrator during empty-provider startup.
There is no first-registrant role assignment or registration link in logs.

In MVP a verified Project member may manage everything in that Project;
finer per-action human rights are deferred. Node knows Project/session scope,
not human roles. Full private management is distinct from MCP session access.

Node supports explicit enforced and auto-approved session-access modes.
The latter automatically approves all valid sessions and their in-Project
actions without manual grants. Project isolation, active session binding,
validation and human infrastructure rights remain mandatory. Only full
management changes mode; automatic decisions grant no management/approver
authority and become no permanent grants when enforcement resumes. See
[mode contract](session-access-modes.md).

In enforced mode, grants and approver authority target AgentSession UUIDs. Caller metadata
does not prove unique agents/chats; new sessions inherit nothing. Only
human/operator management appoints approver sessions; they cannot appoint
others, self-approve the requesting session, cross Nodes or gain upstream
control-plane management. Each grant has independent scope/deadline.
Activity updates only idle state; expiry blocks new work while admitted
work finishes, preserving the session/other grants. Explicit stop is separate.
Automatic idle cleanup is post-MVP.

## Control, storage and transfer

All first-party control uses typed gRPC service/Protobuf contracts with
native gRPC and WSS binary RPC adapters. UI/backend uses WSS; internal
services select native gRPC or WSS explicitly by endpoint capability.
WSS preserves RPC semantics without being native HTTP/2 gRPC. No parallel
REST/JSON or selected GraphQL control layer. MCP and provider-native
protocols are preserved. Backend stores management projections, queries
Node active requests for refresh/reconnect, and checks human Node-wide and
Project-wide scope; Node alone owns operational requests/decisions.

Node management requires native gRPC and WSS/binary Protobuf adapters with
one contract, shared use cases/validation and bidirectional commands/results/
events. Either side may initiate connectivity. Trusted private MVP control
needs no additional user/OAuth or caller-login layer; ordinary MCP workloads
cannot invoke full management. Explicit standalone mode may omit MCP OAuth
while retaining sessions/Cedar. Identity failure never silently switches modes.

One logical Project has one UUID everywhere. Node UUID + Project UUID selects
independent local workspace/session/resource/execution state. Project
workspaces are shared by their modules and effectively isolated from other
Projects. Cross-Project/Node transfer uses an external interface, checks both
endpoints and confirms destination integrity before authorized source deletion.

Node owns durable state behind SQLite/PostgreSQL ports and optional local KV.
Shared Team resources are delivered into Node's database for local runtime
use. Control Plane initiates versioned source updates and periodic/reconnect
reconciliation. Node does not poll/fetch secrets per MCP operation; disconnected
Node retains its last applied state, subject to actual provider validity.

## Common files and system tools

Node has a separate persistent common directory readable/writable by all
local Projects without per-entry or individual operational-grant restrictions,
with session attribution, observation/audit and no automatic exposure of
private Project or module data. Private isolation remains mandatory.
System toolchains are a different Node-owned capability: panel configures
the selected tools/versions; Node installs them through default consuming
image/Compose configuration. Agents use system installations read-only;
Project-local environments remain writable. See
[storage and tools](node-storage-and-transfer.md#node-wide-common-directory).

## Engineering quality

Apply [Clean Architecture/DDD](clean-architecture-ddd-briareus.md),
its [reference](ai-agent-workflow/clean-architecture-ddd.md) and
[local quality policy](../../scripts/quality/README.md). Dependencies point
inward. No framework/ORM/network/process dependencies inside domain, direct
foreign persistence imports or business orchestration in routers/components.
UI retains FSD boundaries and public slice APIs.

Production cognitive complexity is at most 15, tests at most 30. Python
functions are typed; Any and ordinary dictionary result contracts are
prohibited. Use named typed results and boundary serialization. Do not
weaken gates, add blanket ignores or keep duplicate implementations to pass.

Complete source work across every owner before tests/fixtures. Scoped static
diagnostics and batched native checks are allowed. Test/fixture work and
aggregate acceptance begin only after separate user authorization. Hooks
and required checks remain enabled.

## Publication and runtime evidence

Work primarily locally and publish coherent owned batches after local
runtime/lint/type/test/hook validation of the exact outgoing revision.
No approval per ordinary push/scoped Dev deployment is needed within the task.
Avoid tiny pushes, repeated unchanged CI and unverified peer source. Preserve
actual repository protections; main is Development where ordinary push is allowed.

Source, successful build, health and local stubs are not complete product
acceptance. Verify actual consumer paths and scoped rollout/recovery/rollback.
No documentation change authorizes Production, speculative resets, secret
inspection, a global Compose restart or unrelated infrastructure access.

## Existing data and deployment scope

Preserve existing identity/session continuity, databases, volumes, files and
credentials until qualified replacement/migration. Owners migrate only their
own data. Secrets do not enter Git/images/Compose/logs or tool responses.

Infrastructure operations are restricted to the approved Briareus Development
scope in [access policy](../operations/BRIAREUS_DEV_ACCESS_SCOPE.md), including
its exact app identities and prohibitions on viewing unrelated resources or
plaintext secrets. Source target paths are not evidence of saved deployment
configuration. Do not promote uncommitted peer source or reset live data.

Detailed contracts: [topology](infrastructure-hands-shared.md),
[product](target-project-platform.md), [identity/access](identity-and-session-access.md),
[storage](node-storage-and-transfer.md) and [resources](resources-and-secret-sources.md).
