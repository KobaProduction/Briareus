---
name: server-project-workflow
description: Use Briareus Server to open, clone, build, or modify project sources without duplicate repository folders or lost work.
---

# Canonical project workflow (Server Hand)

Use this skill for any request to open a project, run commands against a Git repository, develop code, or create a Server workspace.

1. Identify the intended remote repository `owner/name`. Its canonical checkout is **exactly** `/workspace/projects/<name-lowercase>`. The Server workspace ID is `<name-lowercase>`, not a task name, date, agent name, or `<name>/repo`.
2. Call `workspace_list` and inspect the existing folder before using `workspace_create`. When it exists, inspect `git remote -v`, `git status --short --branch`, `git branch -vv`, and `git worktree list` with `terminal_exec`.
3. If the existing checkout matches the requested remote, reuse it. If the path belongs to something else or has uncommitted/unpublished work, stop and resolve ownership instead of overwriting, deleting, or inventing a suffix.
4. If missing, prefer the authorized GitHub/GitLab Hand's checkout into mount-relative `projects/<name-lowercase>` with `mode=git` and `overwrite=false`. Do not manually make an extra `repo` folder.
5. Before changing code, read the repository's `AGENTS.md`, otherwise `CLAUDE.md`, then `README.md`, and follow its documentation routing. Read parent project instructions if present.
6. For concurrent tasks create a distinct branch and a **linked worktree under the canonical repository's ignored `.worktrees/`**, not a second clone or workspace.
7. Run the repository's relevant checks, respect Git hooks and publication authority, and report exact tested scope. Preserve uncommitted work, unique branches, jobs and artifacts; clean only verified disposable resources.

A skill is guidance, not a server-side guard. Do not assume `workspace_create` or `terminal_exec` currently enforces Git-repository naming.
