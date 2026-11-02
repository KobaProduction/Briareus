# ADR 0002: Project-scoped Terminal workspaces

Status: accepted

## Decision

Terminal is a Node-managed MCP module with persistent Project workspace,
home/job state and process/log operations. Files, Terminal, Browser and
other modules of one Project share that workspace. Other Projects' files,
profiles, homes and credentials remain inaccessible to its workload.
Non-root alone does not establish isolation.

Node's separate common directory is intentionally readable/writable by all
local Projects, without per-entry or individual grants, with observation/
audit and no automatic publication of private Project or native analysis
data. It is not a private Project root. Node system tools are separately
configured through the panel and automatically installed in consuming
image/Compose definitions; workloads use their installation read-only.

Sessions use the Project filesystem under the selected access mode:
current operation/resource grants in enforced mode, automatic approval of
valid in-Project actions in auto-approved mode. Working directories,
repositories and Git worktrees are subdirectories, not independent Projects.
They do not own duplicated Project trees or inherit grants. Work admitted
before grant expiry in enforced mode may finish; new work uses that mode's
current access decision. Explicit
cancel/stop is separate. Automatic idle cleanup is post-MVP.

Cross-Project/Node file movement uses the external interface with endpoint
checks, confirmed destination and authorized source deletion. Preserve
persistent data across recreation and qualified moves.

## Consequences

Mount/process boundaries must enforce isolation; paths, symlinks and shared
homes cannot expose another Project. Device/container privileges require
explicit Node/operator placement. MCP sessions do not gain full management.

See [Terminal requirements](../architecture/terminal-workspaces.md).
