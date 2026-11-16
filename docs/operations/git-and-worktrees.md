# Git and workspace rules for agents

**Authoritative workspace policy:** `/workspace/projects/AGENTS.md` (read the file on the active Server). This document is its Briareus V1 implementation guide, not a replacement.

## Canonical checkout

The one Briareus checkout is `/workspace/projects/briareus`. Its directory follows the Git repository name. Inspect `git remote -v`, `git status`, `git branch -vv` and `git worktree list` before acting. Do not create `briareus-registry-<date>`, `briareus-v1-main`, `briareus-triage` or an extra `projects/<id>/repo`.

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
