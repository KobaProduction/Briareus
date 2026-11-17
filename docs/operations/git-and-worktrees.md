# Git and workspace rules for agents

**Owner for Briareus V1 workspace guidance:** this document. It describes the required agent workflow; existing Server/GitHub/GitLab tools may still accept an incorrect checkout destination. Client instructions are **not** an enforcement boundary. Implement and test canonical-path validation at the checkout-owning MCP tool before treating the rule as guaranteed.

## Canonical checkout and preflight

For a Git remote `owner/repository-name`, the sole canonical full checkout is
`/workspace/projects/<repository-name-lowercase>`, corresponding to MCP
`destination="projects/<repository-name-lowercase>"`.
Example: `ArthurKoba/heating-station` → `/workspace/projects/heating-station`.
Do not append dates, agent names, task names or `/repo`.

Before creating a directory or cloning:

1. List existing Server workspaces/directories and inspect the intended canonical path.
2. If a Git checkout exists, verify `git remote -v`, `git status`, `git branch -vv` and `git worktree list`; reuse it if the remote matches.
3. If the path belongs to a different remote, contains non-repository files or is otherwise ambiguous, **stop** and resolve the collision explicitly. Never overwrite, delete, or invent a suffixed alternative.
4. Only when the path is free, use provider checkout with `mode="git"` and `overwrite=false` at the canonical mount-relative destination. Do not create a second checkout through `workspace_create` or an extra `projects/<task>/repo`.

The canonical Briareus checkout is `/workspace/projects/briareus`. A Server
workspace ID selects a command/job context; it is not evidence that an additional
repository clone is needed. This applies to checkout requests through GitHub,
GitLab and ordinary Server terminal Git operations.

## Parallel development

For parallel tasks, from the canonical checkout:

```sh
git worktree add -b fix/example .worktrees/fix-example v1
git worktree list
```

The canonical repository's `.git/info/exclude` should ignore `.worktrees/`. Every agent gets a distinct branch/worktree and disjoint ownership; no concurrent edits to the same checkout. A branch or worktree with uncommitted changes must be reviewed before cleanup.

## Publication and cleanup

Make coherent commits, run the relevant validation against the staged/outgoing revision, and push only after required checks and GitHub branch protections. GitHub App local authorization is handled by the existing provider helper; never embed credentials in commands or docs.

When done: verify integration of the change; inspect status and refs; `git worktree remove .worktrees/fix-example` **only if clean and no longer needed**; `git branch -d fix/example` only if merged. Never indiscriminately `git clean -fdx`, reset a colleague's work or delete a unique unmerged ref. Separate historical Git bundles are recovery assets, not active branches.

Temporary diagnostics should not become separate Server projects; use ignored, short-lived files under the canonical repository or `/tmp`. Do not delete live browser profiles, credentials, server-side job data or other owners' resources. These rules apply to every Hand and the control plane.
