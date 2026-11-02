# Project Files read admission

This section describes private Project reads. The separate Node-wide common
directory is readable/writable by all local Projects without individual
grants or per-entry restrictions in either mode. Common reads bind the active
session and exact Node shared resource for observation/audit; path/link
validation cannot expose private Project or module data. See
[common storage](../../architecture/node-storage-and-transfer.md#node-wide-common-directory).

Files resolves the current session's Node UUID + Project UUID to the owning
Project workspace and canonical resource. It cannot select another Project
from a caller path, metadata, public header or friendly label.

Before starting a read, Node Access binds it to an active Node/Project
session and canonical resource. In enforced mode it checks the applicable
current grant with Cedar, scope and revision. In auto-approved mode it
automatically approves in-Project reads without a manual grant. Project
isolation is mandatory in both modes; see the
[mode contract](../../architecture/session-access-modes.md). Apply the
configured transport identity/audience requirements; explicit standalone
mode does not fabricate a human identity. Missing session prompts lifecycle
creation; in enforced mode creation alone grants no read permission.

Files and its runtime enforce actual Project filesystem isolation, traversal/
symlink protection and ownership of the opened resource. Do not mount the
Node parent of all Project workspaces into an untrusted Project workload.
Workspace sharing with Terminal/Browser is confined to the same Project.

Admission is bound to the exact read and resource. A read admitted and started
in enforced mode before grant expiry may finish; passive expiry is not cancellation or a
reason to use another grant's later deadline. Later reads need fresh admission.
Explicit cancellation/session stop follows its own authorized lifecycle.

Preserve canonical resource/operation binding and integrity during I/O.
Do not expose host paths, sibling Project data, secret values or invented
bearers in the result. Return only the intended bounded content/metadata
through the module contract and distinguish actual errors from success.

Cross-Project/Node file transfer is a separate external management scenario
with both endpoint checks and target Node/Project UUID. Normal read/copy/
terminal paths cannot bypass that boundary. A copied file transfers no grant.

See [session decisions](../../hands/node/session-access.md),
[Files](../../file-service.md) and
[storage/isolation](../../architecture/node-storage-and-transfer.md).
