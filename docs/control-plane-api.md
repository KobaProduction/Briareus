# Control Plane backend RPC and UI

Control Plane UI is the user interface. Control Plane backend owns human
authentication integration, management orchestration and Node event
projections. `Control Plane API` is an existing component/path name, not a
REST architecture requirement. Backend uses owner application contracts
without opening Node databases or becoming their session-policy authority.

## Identity and human scenarios

All sign-in, MFA and recovery screens are native Control Plane UI.
Authentication follows UI → Control Plane backend → private Rauthy.
The backend owns provider sessions/challenges and the pinned protocol;
Rauthy verifies credentials and owns identity tokens/groups/roles. No
separate infrastructure Authorization service exists. The backend does not
implement a second password verifier or identity-token issuer.

In MVP, infrastructure checks current human access to the Project/group.
A member can manage everything within that Project; finer per-action human
permissions are later functionality. Project membership is not permission
to manipulate unrelated Projects or all Node host resources.

## RPC contracts

Browser UI uses typed backend service methods over WSS/binary Protobuf.
Internal first-party services use native gRPC or WSS adapters of the same
gRPC service/Protobuf contracts, selected explicitly for the endpoint.
WSS is a separate RPC transport adapter, not native HTTP/2 gRPC. Application
use cases, authority, validation, results/errors and operation identity are
shared. REST/JSON CRUD is not a parallel control interface; GraphQL is not
selected. Existing HTTP routes require qualified consumer migration, not
speculative removal. External MCP and provider-native protocols remain
their own supported interfaces.

## Node management

The Control Plane backend is the central management coordinator. Node owns
and durably records all local AgentSessions, requests, grants, decisions and
execution state. The backend stores registry/domain state and a projection
of Node events for UI queries; that projection is not an execution grant
store and cannot authorize an effect on a disconnected Node.

Node-wide views group authorized data by Node, Project and session.
Project-wide views group one logical Project across its known Node
placements, including absent/offline placements without inventing state.
Human Node-management scope and Project membership are checked in
infrastructure before querying or commanding a Node. A Project view reveals
only accessible Projects; selecting a Node never grants access to all its
Projects. These scopes describe human management, not roles inside Node.

Nodes publish request/session/grant changes through the persistent binary
RPC channel. The backend records Node UUID, Project UUID, session/request
identity, revision and event cursor, and updates UI notifications/views.
UI shows the claimed agent metadata as unverified context and distinguishes
last observed state from live Node-confirmed state. Disconnection marks
the projection stale; it never turns pending into approved or erases a
request merely because no event has arrived.

Management RPC must query the complete current active-request set with
bounded pagination and explicit Node/Project/session/status filters, fetch
an exact request/session, and reconcile revisions/cursors. Manual refresh
and reconnect obtain authoritative Node state through these methods rather
than depending exclusively on events. Decisions return to Node with exact
request identity/revision; UI marks completion only after Node confirms it.
Method names and pagination DTOs must be versioned with the shared contract;
this requirement does not invent currently deployed endpoints.

The API adapts authorized UI scenarios to the relevant Node owner contracts.
Node Gateway management supports native gRPC and WSS/binary Protobuf, one
contract and shared use cases over persistent bidirectional command/result/
event channels. Either side may initiate connectivity.

Node knows local Projects and sessions, not human users/Teams. It emits
pending-access events; infrastructure updates user notifications and sends
authorized decisions back. Node Access persists/enforces session grants
with Cedar in enforced mode. Its auto-approved mode confirms valid sessions
and their in-Project actions without manual review, while retaining Project
isolation. The mode belongs to Node, not an API-only bypass; see
[mode contract](architecture/session-access-modes.md).
Automated approver sessions operate only within their Node/scope.

## Files and resources

Backend RPC manages Node system-tool selection/version/configuration and
reports desired versus observed installation state. Node installs selected
tools through consuming image/Compose definitions; agents use system
installations read-only. A Node-wide common directory is separately writable
by all local Projects without per-entry/individual-grant restrictions and
is observed/audited; it is not system-tool installation or private Project
storage. Common data is never auto-populated from private files/credentials.

The API does not mount every Node workspace or directly open Node databases.
Project files and runtime operations go through Node contracts. Transfers
identify both endpoint Node/Project scopes, even on the same Node.

External-service connections can be Node-local or explicitly bound to a
shared Team resource from infrastructure. Control Plane UI/API manages
these sources through owner interfaces, not a second secret database.
Shared values are delivered into Node durable storage; working MCP operations
resolve them locally. Control Plane initiates change delivery and periodic/
reconnect version reconciliation over the existing binary management channel.
Node does not poll the secret catalog or depend on it for each operation.
Ordinary metadata responses never reveal token values or provider secrets.
See [resources and secret sources](architecture/resources-and-secret-sources.md).

## Delivery

Apply [source/test and publication policy](../scripts/quality/README.md).
Source DTOs, health and local stubs are not proof of deployed login or
protected operations. Preserve data, approved deployment scope and rollback.
