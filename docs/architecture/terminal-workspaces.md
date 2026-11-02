# Terminal workspace architecture

Status: Terminal workspace and execution requirements for Project-scoped Node runtime; not evidence of deployed isolation.

## Goal

Give agents a persistent Linux development environment that is fast to use for source
inspection, patching, local Git workflows, builds, Python environments and interactive
hardware work.

Project filesystem/runtime isolation is mandatory. A non-root user alone
does not prove that one Project cannot access another Project's files,
home, browser profile or credentials. Runtime configuration must enforce
the selected Project workspace boundary.

## Topology

```text
ChatGPT / MCP client
        |
        | /terminal/mcp
        v
gateway
        |
        v
terminal
   |
   +-- persistent /workspace
   +-- persistent /home/agent
   +-- scoped outbound network under Node/Project policy
   +-- same Project workspace as Files, Browser and Web modules
   +-- optional deployed UART/USB devices
```

Node manages the Terminal module and binds each execution to its local
Project and AgentSession. A shared runtime implementation is allowed only
if actual process/filesystem boundaries isolate Projects; it must not expose
a global all-Project filesystem to a Project command.

## Project filesystem and working directories

Each Project has its own persistent workspace shared by its Files, Terminal,
Browser and other modules. Inside the Project, callers may organize source,
scratch, artifacts, repositories, Git worktrees and toolchain subdirectories
under the selected session-access mode. These are working directories inside
the Project, not additional Projects or per-agent isolation roots.

`/workspace` inside a scoped workload denotes that Project's root, not the
Node parent of all Projects. Terminal home/cache/config/SSH/job state is
also Project-scoped. Persist the owning Project state across container
recreation without exposing sibling Projects or resetting existing data.

Existing workspace identifiers and cwd are resolved within the current session's
trusted Project context. They do not create a new Project or authorize
listing sibling workspaces. Enforce traversal/symlink and runtime/mount
boundaries; a directory naming convention alone is not isolation.

Cross-Project file/directory transfer uses the external interface with
explicit target Node/Project UUID, even on the same Node. Ordinary terminal
commands cannot bypass that interface via host/sibling paths.

## MCP surface

### Status and Project working directories

- `terminal_status`
- `workspace_list`
- `workspace_create`
- `workspace_info`
- `workspace_delete`

Existing `workspace_*` wire names identify working directories inside the
current Project. They cannot create, enumerate or delete Node Projects or
select another Project root. Project lifecycle belongs to management RPC.
Deleting a working directory requires the applicable operation decision and
refuses while jobs use it. A force flag grants no cancellation authority:
affected jobs must first be stopped through a separately authorized command.
The Project root and module-private native analysis stores are not targets
of this working-directory deletion. Preserve shared Project data and other
sessions' active work. Existing wire names are not renamed by this document.

### Quick commands

`terminal_exec(workspace_id, command, cwd, env, timeout_seconds)`

Use for grep, git status/diff, short scripts and quick tests.

Return structured:

- exit code / signal;
- stdout;
- stderr;
- timestamps/duration;
- truncation metadata.

### Jobs: universal process abstraction

All long-running and interactive work uses jobs:

- `job_start(workspace_id, command, cwd, env, interactive=false, label="")`
- `job_status(job_id)`
- `job_read(job_id, cursor=0, max_bytes=..., wait_seconds=0)`
- `job_write(job_id, data)`
- `job_resize(job_id, cols, rows)`
- `job_wait(job_id, timeout_seconds)`
- `job_cancel(job_id, grace_seconds)`
- `job_list(workspace_id, state, offset, limit)`
- `job_delete(job_id)`
- `job_cleanup(older_than_hours, dry_run, limit)`

`job_write` and `job_resize` are valid only for interactive jobs.

A build is simply a job. A shell is an interactive job. A development server is a job. A
serial console is an interactive job running a serial utility.

## Incremental log contract

This is a first-class optimization, not an afterthought.

Each job output stream is append-only and addressed by a byte cursor.

Example flow:

```text
job_start(...) -> job_id=abc
job_read(abc, cursor=0)    -> output="...", next_cursor=1842
job_read(abc, cursor=1842) -> output="only new bytes", next_cursor=2310
job_read(abc, cursor=2310) -> output="", next_cursor=2310
```

The response also reports:

- `eof` / process state;
- whether older output was truncated by retention;
- current total output size;
- optional stdout/stderr stream identity when not PTY-backed.

This lets an agent poll a long build without repeatedly consuming the full log. A caller
may explicitly request from cursor 0 when the complete retained log is needed.

Logs remain available after process exit and can be deleted individually or cleaned up in
bounded batches by age. Job listings are paginated so a long-lived terminal does not push
its complete process history into every agent/Admin request.

## Interactive jobs

Interactive jobs allocate a PTY. The agent reads output through the same cursor-based
`job_read`, writes stdin with `job_write`, and changes terminal size with `job_resize`.

A PTY belongs to a Terminal job, without another Terminal-specific session
entity. The job is an execution resource of its owning Node/Project
AgentSession; it does not replace the AgentSession access/lifecycle model.

This supports:

- interactive shells;
- REPL/debuggers;
- installers;
- text-mode tools where appropriate;
- UART/serial programs.

## Serial/UART

Serial is deliberately not a separate MCP subsystem.

The operator exposes a device to the terminal container using normal Docker/Linux device
permissions. The image contains a normal serial utility.

The agent then starts, for example, an interactive job conceptually equivalent to:

```text
picocom <device> --baud <rate>
```

After that, all interaction is ordinary `job_read` / `job_write` / `job_cancel`.

The same model also works for flashing/debug tooling that needs a passed-through USB
device: it is just another command/job once Linux permissions permit access.

## Base development image

System tools are a Node-owned, panel-configurable capability. The list below
is the baseline desired tool set, not an immutable list or proof of current
installation. Node automatically installs selected tools/versions through
the consuming module image/Compose lifecycle and reports observed status.
Operators may add, remove and configure tools through management RPC. Agents
use the installed executables read-only as system tools; Project-local
dependencies/environments remain writable. A tool selection change affects
its actual consuming containers, preserving Project and analysis data.

Node additionally provides a separate persistent common directory readable
and writable by all Projects, with attributable observation/audit and no
per-entry/session-grant restrictions. It is not the read-only system-tool
installation, another Project's private root, home or browser profile.
Private data/credentials are never automatically copied there. Common data
sharing does not create a private cross-Project filesystem path. See
[Node storage](node-storage-and-transfer.md#node-wide-common-directory).

The image should be useful without package installation during routine work.

Baseline:

- bash/sh;
- git + OpenSSH client;
- curl/wget;
- grep/ripgrep/find/sed/awk;
- patch/diff/rsync;
- jq;
- tar/zip/unzip/xz;
- make;
- gcc/g++/binutils;
- cmake/ninja/pkg-config;
- Python + uv + pip/venv;
- Buildroot/OpenIPC common prerequisites;
- picocom and pyserial.

Project-local dependencies are allowed under the normal user account.

If a system dependency is missing, the agent gets the real command error and reports the
missing package instead of attempting privilege escalation.

## Git

Local Git should be fully usable because repository inspection through a filesystem is much
cheaper than repeated provider API calls.

Typical work:

- clone/fetch where credentials permit;
- status/diff/log/blame;
- branches/worktrees;
- apply patches;
- rebase/cherry-pick when appropriate;
- build/test from the working tree.

GitHub/GitLab MCP remains available for provider-native repository/PR/MR operations. We do
not need to duplicate all of that inside Terminal.

## Files integration

Files and Terminal serving one Project use that Project's persistent
workspace. Other Projects are not mounted or directly accessible. Normal working files
therefore require no import/export operation: a file uploaded, downloaded, moved or edited
through Files is immediately visible to Terminal by path, and files produced by Terminal
are immediately visible to Files.

There is no separate Files object store. Files and Terminal are two interfaces over the
same Project working filesystem.

Terminal job metadata and retained process logs live under `/home/agent/.terminal`, not
inside the current Project workspace.

## Control Plane UI

Add one Terminal section, not a large configuration product.

Show:

- workspaces;
- active/recent jobs;
- interactive/non-interactive;
- command/label and cwd;
- state, exit code and duration;
- last activity;
- current output tail;
- installed tool availability and free disk;
- Linux groups and persistent Git/SSH setup indicators;
- serial devices visible to the container and whether they are readable/writable;
- cancel, retained-log delete and old-job cleanup actions.

Dashboard cards may show running jobs and failed recent jobs.

System tool selection is configured through panel/Node management and
materialized by Node in consuming images/Compose. Linux permissions, device
mappings and runtime privilege remain Node/operator configuration, not
unverified UI action hints. Missing packages/groups/device mappings/mounts
are reported as unavailable; applying them follows the owning container's
image/Compose lifecycle and preserves independent module boundaries.
User-space dependencies, Git configuration and SSH keys remain agent-manageable inside the
persistent home/workspace without root.

## Safety baseline

Keep it intentionally simple:

- run as non-root;
- no sudo by default;
- do not run the container privileged by default;
- package/device permission failures are surfaced normally;
- operator changes permissions or Compose configuration when a task genuinely needs it.

Project filesystem/runtime isolation remains mandatory even when an agent
has authorized mutation tools. Container/device privileges and access to
private management/storage remain outside ordinary Project workloads.

## Observability

Reuse current OpenTelemetry integration with `mcp.scope=terminal`.

Terminal intentionally does not send command arguments, stdin or job output into the
Control Plane API MCP-call payload audit. Durable job metadata/output is already retained in the
terminal workspace, while OpenTelemetry records operational metrics without command bodies.

Useful metrics:

- running/completed/failed jobs;
- job duration;
- command failures;
- output bytes;
- active interactive jobs;
- workspace disk usage.

Do not export command bodies, stdin, credentials or full output as telemetry attributes.

## Implementation order

1. terminal runtime + persistent volumes + non-root image/toolchain;
2. workspace directory lifecycle;
3. `terminal_exec`;
4. jobs with durable cursor/delta logs;
5. PTY input/resize on interactive jobs;
6. shared Files/Curl workspace access;
7. typed Control Plane API/UI adaptation;
8. scoped telemetry and, only in the separately authorized aggregate phase, tests;
9. validate UART by passing one real device and running it as an interactive job.

Acceptance requires actual Project filesystem/runtime isolation and the
Node session-access mode in addition to working Terminal operations.
Auto-approved mode confirms valid in-Project actions without manual grants,
while Project isolation always applies; see
[mode contract](session-access-modes.md). Idle
shutdown/resource garbage collection is post-MVP; it does not defer the
Project boundary or permit direct access to another Project's files.
