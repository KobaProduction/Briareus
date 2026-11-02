# Node storage and file transfer

## Ownership and autonomy

Each Node owns its persistent filesystem/workspaces, local Projects,
AgentSessions, review metadata, requests/grants/revocation, deployed-module
state and execution journal. Connected mode does not move this ownership
into the central Resources database. Standalone execution needs no central
storage service or globally mounted workspace. Node can start and execute
without the Panel; infrastructure only adds management, human users/groups/
Teams and collaboration. Agents use Node-local sessions through MCP tools.

Each storage owner keeps its own files, databases and private runtime data.
Another Node does not read that storage directly. Reusing selected data on
another Node requires an explicit transfer/import/export owner interface;
matching Project UUIDs or Panel attachment never makes storage global.

Infrastructure owns its users/Teams, central Project/Node registry and
provider/domain storage. It may observe or orchestrate Nodes through the
management contract but does not open their database or filesystem directly.

## Project identity across Nodes

A logical Project has one Project UUID in Control Plane and on every Node
where it is placed. Node UUID + Project UUID identifies its local workspace,
session/grant state, bindings and execution records. Do not introduce a
separate local Project UUID mapping or infer identity from a display name.

The same Project UUID on another Node has independent files/runtime state
and permissions. It implies no shared mount, automatic synchronization,
session inheritance or cross-Node approver authority. Transfer can target
the same Project UUID on a different Node or another Project UUID on the
same Node; both endpoint Node/Project scopes remain explicit.

## Per-Project workspace isolation

The isolation unit is the local Project, identified by Node UUID + Project
UUID. Its Project filesystem is the persistent root; `workspace` in an
existing container path or wire field means that root or a relative working
directory inside it, never another independent Project. Repositories,
Git worktrees, builds, toolchains and agent working directories are ordinary
Project subdirectories. Creating one does not create a Project or a new
permission boundary. Sessions share the Project files under its access mode.

Each local Project has its own persistent workspace. Files, Terminal,
Browser and other MCP modules serving that Project use the same Project
workspace; sessions are not separate owners of duplicate filesystem trees.
Within the Project, ordinary operations can create subdirectories and
work with files according to the selected session-access mode: explicit
grants in enforced mode, automatic approval in auto-approved mode. Effective
Project isolation remains mandatory in both; see
[mode contract](session-access-modes.md).

A session's Project context selects the workspace. Caller paths, filenames,
workspace labels and metadata cannot switch the Project or expose siblings.
Project A execution cannot read/write/list Project B workspace, runtime
files, browser profile, terminal home or credentials. Enforce effective
filesystem/runtime isolation, not merely a naming convention or UI filter.
Never mount/expose the parent containing every Project to an untrusted
Project workload. Reject traversal, symlink and other boundary escapes.

Normal MCP file/process tools operate only within their current Project.
Access to another Project's private files is an explicit external management/transfer use case,
not a path like ../other-project or an agent-selected absolute host path.
Browser downloads, terminal output files and Files views agree on the same
Project workspace without exposing another Project's runtime data.

Analysis engines such as Ghidra and radare2 keep their own durable native
projects/databases in module-owned private storage, partitioned by Project.
Their storage survives container replacement and is not an ordinary Files
or Terminal working directory. Import/export exchanges selected files with
the current Project filesystem through owner contracts. No module mounts
another engine's private store for direct file manipulation.

## Node-wide common directory

Node provides a persistent common directory, separate from every Project's
private root and from module-private storage. All local Projects can read,
write, create, rename and delete its entries. Do not add per-Project,
per-entry or individual operational-grant restrictions inside this common
namespace. Sessions remain the source of actions for observation/audit;
automatic access to common storage is independent of enforced/auto-approved
approval for private Project operations. Common storage is deliberately
shared, not a way to select or mount another Project's private directory.

Node exposes its usage/state to management and records attributable changes
and failures without logging file contents or secret values. Projects see
the same common contents on that Node; it is not replicated across Nodes.
Content placed there is readable and mutable by all local Projects. Do not
automatically copy private files, homes, profiles, credentials or module
databases into it. Audit and UI clearly distinguish this shared namespace
from Project-private files. Publication to common storage and later import
are shared-data operations; they carry no session grant or management right.

This is a temporary common-data capability, not the system-toolchain store.
Its shared visibility does not relax traversal/symlink boundaries or expose
the parent of private Project roots. Cross-Node transfer still uses the
explicit endpoint-scoped transfer contract. Private Project-to-Project
transfer retains both endpoint checks; the common directory is not presented
as a direct path into another Project's private filesystem.

## Node-managed system tools

Node owns installation and configuration of system toolchains/runtimes,
managed through the panel and the same trusted management RPC. The selected
tools and versions form the default image/Compose runtime configuration of
the consuming modules; ordinary use must not require each agent to install
Python, Node.js, uv or another selected system tool into its Project first.
Operators can add, remove and configure tools; Node applies the resulting
installation/update through the owning image/container lifecycle and reports
actual version, availability and failure state. Do not claim a tool is
installed merely because it appears in desired panel configuration.

Workloads use installed system tools as ordinary system executables, with
the installation read-only to agents. Project-local dependencies, virtual
environments and caches remain writable inside that Project; the common
directory remains writable as described above. Changing system tools is
management, not modification of the common folder by an MCP command. A
configuration update affects only consuming containers; it is not a global
Node/database restart. Existing files and private analysis projects survive
tool/image/container replacement.

## Persistence ports

Node application use cases depend on typed inward-facing persistence ports.
SQLite and PostgreSQL adapters implement the same owner invariants. Domain
code does not import either engine, ORM, filesystem or network transport.
Select the adapter explicitly and preserve its state across normal restarts.
A failure does not authorize automatic backend fallback, empty-state reset
or replacement of existing data.

A PostgreSQL dependency belongs to the Node-managed runtime/storage contour;
it is not the central Resources journal. SQLite files belong to persistent
Node storage. Keep operation identity, transactional grant decisions,
revocation/revision, ordered events/cursors, writer exclusivity and replay
semantics consistent across adapters. Backup/migration is a deliberate,
scoped operation with qualified recovery and rollback.

Node may use its own Valkey/KV and scratch databases for activity tracking,
cache or computation. Do not require them merely to add another pattern.
Ephemeral cache/idle state is distinct from durable authorization decisions;
cache loss never grants access or extends a hard grant deadline.

## Delivered resource values

Team-shared/external resource values are stored durably in the Node database
with their explicit source/binding/version. Runtime use is local. Control
Plane initiates updates and periodic/reconnect reconciliation over the binary
management channel; Node does not poll or fetch secrets per MCP operation.
Disconnection preserves last applied local state. Remote changes take effect
after delivery; provider credential validity is independent. See
[resource delivery](resources-and-secret-sources.md).

## File capabilities

Node contracts include upload/download and explicit file or directory
transfer with source and target Node UUID, Project UUID and Project-relative
resource/path. `target_project_uuid` identifies the destination Project;
`target_node_uuid` may identify the source Node itself. These are logical
selectors, not trusted authority or host filesystem paths.

One interface covers cross-Node transfer and transfer between Projects on
the same Node. A same-Node destination still requires independent source/
target Project checks and the external transfer boundary. Ordinary MCP
file/process tools cannot bypass this through direct filesystem access.
Destination placement and overwrite behavior are explicit; do not infer
them from a filename or accidentally replace another Project's files.

Binary Protobuf contracts serve native gRPC and WSS adapters, sharing the
same use cases and validation. Transfer has a typed operation identity,
source/destination scope, progress/outcome and confirmed completion. Use
bounded streaming/chunks rather than assuming a whole file fits in a single
control message. Reconnection/retry preserves identity without duplicate
writes or silent overwrite of unrelated data.

The transfer use case accepts a selected file, a directory or an explicit
list of Project-relative entries. One logical operation reports per-entry
progress/outcomes and a final manifest; batch completion cannot conceal a
failed or partial entry. Native analysis import/export uses this same typed
data-transfer boundary where applicable. Archive packaging is an optional
transport optimization, not a required user workflow or permission shortcut.
If used, extraction validates every entry against the destination Project
root and cannot introduce traversal or link escapes. The concrete archive
format and wire method names are not selected by this requirement.

## Transfer and movement

The external management/transfer use case checks both source and target
Node/Project/resource scope, even when both endpoints are on the same Node. Session grants
and approver authority are Node-local and do not travel with a file. Copying
content does not attach a Node to a central Project or grant another session
access. The orchestrator does not bypass endpoint checks.

Movement consists of confirmed destination write/integrity followed by an
explicitly authorized source deletion. A failed, partial or unconfirmed
transfer retains the source. Report partial outcomes accurately; a lost
reply is not proof that deletion or transfer failed and must not trigger
blind re-execution. Preserve operation identity for reconciliation.

Transfer is an explicit data operation, not automatic replication, shared
mounting, Workspace migration/failover or cross-Node privilege delegation.
The interface supports later multi-Node workflows without requiring those
features to exist implicitly in the first runtime.

## Acceptance boundary

Verify owner state survives restart for the selected adapter and is usable
without central storage; verify Project isolation and grant/deadline
invariants. File acceptance includes upload/download, scoped transfer,
confirmed copy, explicit move/delete and interruption/retry reconciliation.
A source interface or mocked store alone does not establish runtime or live
data-migration acceptance. No existing database, provider volume, workspace
or credential is reset or moved by this document.
