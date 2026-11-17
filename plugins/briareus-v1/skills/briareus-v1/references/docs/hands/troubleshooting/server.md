# Server MCP — workspace, jobs and memory failure modes

**Owners:** [Server MCP](../server.md), [Server source](../../../services/hands/server/README.md);
the [V1 Git/worktree policy](../../operations/git-and-worktrees.md) is the
**single authority** for exact canonical paths, repository collisions and
linked worktrees. Do not repeat its full procedure here.
Generic Bash/PowerShell/SSH command conventions are AI Agent Workflow's
independent `terminal-operations` Skill, not Briareus policy.

## Duplicate checkout or wrong project directory

**Failure:** an agent creates `projects/<task>/repo`, a dated suffix or a
second clone because a Server `workspace_id` was treated as a Git destination.
**Known limitation:** Server workspace creation accepts arbitrary IDs; it
does **not** enforce canonical Git checkout naming.

**Avoid recurrence:** inspect existing workspaces and the canonical path
*before* checkout. Check the remote, branch, working state and linked
worktrees; reuse an existing matching checkout. On a collision or unique
unpublished work, **stop** rather than overwrite or invent a suffix.
For precise path formatting and missing-checkout handling, read the single
[workspace owner](../../operations/git-and-worktrees.md).

## Transport error is not command failure

[Issue #252](https://github.com/KobaProduction/Briareus/issues/252)
records intermittent `terminal_exec`, `job_status` and `job_read` backend
timeouts, DNS errors, `Connection closed` and generic internal errors.
A durable job may continue after a disconnected client; a backend restart
can instead mark it interrupted.

**Avoid recurrence:** inspect the existing job ID, saved status and output
cursor before retrying. Distinguish *running*, *finished with exit code*,
*interrupted* and *unknown after transport loss*. A possibly non-idempotent
operation must **not** be replayed on a transport error without proof it did
not execute. Do not classify an MCP disconnect as a failing pytest suite.

## Exit 137 / cgroup OOM versus host restart

[Issue #367](https://github.com/KobaProduction/Briareus/issues/367)
confirmed a 2 GiB Terminal cgroup `oom_kill=1` and a Bun/Nuxt build
ending in SIGKILL/exit 137. A memory-conscious Bun build subsequently passed
without a second OOM kill. A host reboot also occurred, but **the root
cause of the reboot was not established**.

**Avoid recurrence:** check the actual cgroup limit, `memory.events`,
process exit and concurrent load before choosing a memory-efficient build
mode or changing limits. Do not equate DNS timeout, exit 137 and host reboot;
do not restart the node or increase all budgets based on an assumption.

## Jobs and cleanup

The Server uses process-group lifecycle and bounded completed-job log
retention; its automatic cleanup **does not delete Git checkouts or
workspaces**. Inspect the scoped cleanup preview and preserve active jobs,
uncommitted work, other agents' branches and persistent storage.
The [Server owner](../../../services/hands/server/README.md) controls
current retention settings and exact cancellation semantics.

**Successful diagnosis:** the intended checkout is reused, job execution
state is evidenced, recovery is scoped, and no unrelated data or running
work is lost.
