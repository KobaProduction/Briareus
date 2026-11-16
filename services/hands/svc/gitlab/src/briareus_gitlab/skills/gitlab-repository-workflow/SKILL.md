---
name: gitlab-repository-workflow
description: Discover, clone, review, modify, and publish GitLab projects through Briareus GitLab and Server while preventing duplicate checkout directories.
---

# GitLab repository workflow

Use this skill for GitLab project discovery, checkout, merge requests and local Git work.

1. Call `accounts`, `list_projects` and `project_status` for the correct GitLab account and project path. Check effective permissions and the target branch before changing sources.
2. Resolve the project `namespace/name` and canonical Server checkout `/workspace/projects/<name-lowercase>` (mount-relative `projects/<name-lowercase>`). GitLab namespaces can contain repositories with identical basenames: if the canonical directory would conflict, stop and resolve explicitly; do not fabricate a dated suffix.
3. Call Briareus Server `workspace_list`, then inspect a present checkout with `terminal_exec`: `git remote -v`, `git status --short --branch`, `git branch -vv`, and `git worktree list`. Reuse the matching checkout; never delete an existing project to reclone.
4. Only for a free canonical path, call `checkout_repository(account_id, project, destination, mode="git", overwrite=false)`. Do not nest the clone in `projects/<task>/repo`.
5. Read source instructions completely (`AGENTS.md`, otherwise `CLAUDE.md`, then `README.md` and mandatory linked references) before code changes. Isolate concurrent tasks into branches and linked worktrees below `.worktrees/`.
6. For local Git use `authorize_local_git` when appropriate; never embed tokens. Validate affected changes, respect protected branches and Git hooks, then publish with `push_local_git` only when authorized.
7. Report exact files changed, revision, tests run and missing acceptance checks. Preserve unique work and do not claim a deployment passed from source-only checks.

The current checkout API still needs server-side validation; this workflow does not replace it.
