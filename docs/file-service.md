# Project-scoped Files service

## Workspace ownership

Each Node-local Project owns one persistent workspace. Files, Terminal,
Browser downloads and other MCP modules of that Project operate on the same
working files. A session uses the Project workspace under the selected Node
session-access mode; there is no global workspace shared across all Projects/Nodes and no
mandatory copy per session.

The Project filesystem is the isolation root. Agent working directories,
repositories, Git worktrees, builds and toolchains are subdirectories of
that root, not additional Projects. Existing workspace wire fields/paths
resolve only inside the selected Project; they cannot enumerate or change
other Project roots. Native Ghidra/radare2 analysis projects remain in their
module-owned durable private storage and use controlled import/export.

A module may expose its Project root as `/workspace`, but that container
path denotes only the selected Project. Do not expose the Node parent that
contains other Projects. Project context comes from the trusted session/
owner binding, not a caller-selected host path or label.

Enforced mode requires explicit operational grants. Auto-approved mode
confirms every valid session and its in-Project actions without manual
review; active session binding and Project isolation always apply. See
[mode contract](architecture/session-access-modes.md).

## File operations

Node also exposes an explicitly common persistent namespace, separate from
private Project roots. All local Projects can read/write it without per-entry
or individual grant restrictions. Node observes/audits attributed actions;
contents are intentionally shared and private data is never auto-published.
Common paths cannot escape into another Project's root or private analysis
store. See [common storage and system tools](architecture/node-storage-and-transfer.md#node-wide-common-directory).

Within its approved scope, Files supports status/free space, directory
listing/metadata, bounded reads, content checksums, text/binary writes,
attachment ingress, subdirectory creation and copy/move/delete. Resolve paths
inside the current Project root and reject traversal, symlink and other
boundary escapes. Runtime mounts/process access must enforce the same
Project boundary; an API-only filter is insufficient.

Binary writes validate offset/progress and publish complete files only
after required size/integrity checks. Partial transfer state is not a
completed destination. Preserve operation identity across retries and never
silently overwrite unrelated files.

## Other MCP modules

Terminal uses the same Project workspace for cwd, source, environments and
artifacts. Its private home/job state is Project-scoped, not shared with
another Project. Browser downloads/captures and Web request file input/output
resolve to this same workspace. Project browser profiles and credentials
remain isolated from other Projects; shared files do not imply shared IAM.

Provider-native analysis databases remain private runtime storage. Controlled
import/export may exchange selected Project workspace files; direct mounting
or exposing another runtime/Project's private database is not allowed.

## Cross-Project and cross-Node transfer

Ordinary file/process MCP tools cannot access another Project's private files directly.
External management transfer selects source Node/Project/resource and
`target_node_uuid`, `target_project_uuid` and a Project-relative destination.
Files and directories can move between Nodes or between Projects on the
same Node through this same interface and separate endpoint checks.

Move confirms destination write/integrity before separately authorized
source deletion. Preserve the source when completion is unconfirmed. File
transfer carries no session grant or approver authority and performs no
automatic synchronization. See
[Node storage and transfer](architecture/node-storage-and-transfer.md).

This architecture does not establish an accepted live migration. Existing
workspace files and databases remain protected until scoped transfer and
recovery/rollback are qualified.
