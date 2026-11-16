# Git, canonical checkout and parallel ownership

The authoritative directory rule for the Server workspace is at /workspace/projects/AGENTS.md. Reuse the **one checkout per repository**: /workspace/projects/briareus for KobaProduction/Briareus. Do not create new task/date clones or a separate local project for every V1/V2 or agent task.

For simultaneous work on a different version, use a **linked Git worktree inside the canonical checkout**:

```sh
cd /workspace/projects/briareus
git status --short --branch
git worktree list
git worktree add -b docs/v2-example .worktrees/v2-example v2
```

The .worktrees/ path must be ignored by Git locally. Each agent has its own task branch/worktree and exclusive file/module ownership. Before cleanup, verify tracked/untracked changes, local-only commits, active jobs and dependence by another agent. Remove clean finished worktrees with `git worktree remove`, and delete a task branch only after confirmed integration. Do not force-reset or remove another owner's work.

**Two distinct Project concepts:** In the Server development filesystem, `/workspace/projects/briareus` is a repository checkout. In the **target V2 product**, a logical Project is a UUID-bearing domain entity with one private Node-local filesystem per Node placement. A Git worktree, task/build directory or Python environment **inside that Node Project** is not a new logical Project or access boundary. The two systems must not be conflated.

Coordinate cross-owner contract changes before touching shared code. Make coherent batches and follow the [V2 release policy](release-and-scope-policy.md), required checks and remote Git protections. Do not publish to Production or deploy anything merely because the branch is named v2.
