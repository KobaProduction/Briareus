# Control Plane Project file content

Control Plane API adapts a current human Project scenario to the owning
Node file contract. It does not mount all Node workspaces, open Node
databases or treat a browser-selected absolute path as authority.

One logical Project uses one UUID everywhere. Node UUID + Project UUID and
the canonical file/resource select the local placement. Infrastructure
checks current human membership; Node resolves only that Project workspace
and enforces its applicable local operation/owner boundary.

Normal MCP reads use Node Access and the selected session-access mode.
Enforced mode requires the matching current session grant at admission;
auto-approved mode automatically confirms valid in-Project reads without
manual grants. Project isolation and active session binding always apply.
See [mode contract](../../architecture/session-access-modes.md). A read admitted/started before grant expiry may finish; do not
cancel it solely because the grant deadline elapses during I/O. Explicit
stop/cancel follows its own authenticated management/session contract.
Resource/path integrity and exact operation binding remain required.

Return intended bounded bytes/metadata with correct content disposition/type,
without exposing host paths, tokens or unrelated Project content. Untrusted
filenames/headers cannot choose another owner or reveal private runtime data.
Cancellation/error results must not be misreported as complete content.

Other Projects' files use the explicit external transfer interface, not
traversal or direct local disk. The same interface covers two Projects on
one Node and cross-Node movement, with both endpoint checks.

See [Files](../../file-service.md),
[Node storage/isolation](../../architecture/node-storage-and-transfer.md)
and [session access](../../hands/node/session-access.md).
