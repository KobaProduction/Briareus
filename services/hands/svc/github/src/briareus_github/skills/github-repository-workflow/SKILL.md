---
name: github-repository-workflow
description: Discover, clone, review, modify, and publish GitHub repositories with Briareus GitHub and Server tools while preserving canonical paths and history.
---

# GitHub repository workflow

Use this skill for repository searches, source edits, clone/checkout, PR review, publication, and GitHub Actions diagnostics.

1. Call `github_accounts` and `github_agent_list_repositories` for the selected account. Inspect private repositories through the authorized MCP account rather than assuming public browser results are exhaustive.
2. Confirm the repository `owner/name`, correct selected account, permissions, branch, and remote. Avoid inferring authorization from a visible repo name.
3. Before checkout, use Briareus Server `workspace_list` and `terminal_exec` to inspect the **existing** `/workspace/projects/<name-lowercase>`, remote, working status, branches and linked worktrees. Canonical MCP destination is `projects/<name-lowercase>` (never `projects/<task>/repo` or a dated suffix).
4. Reuse a matching checkout; stop on collisions. Otherwise call `github_checkout_repository(account_id, repository, destination, mode="git", overwrite=false)`. Do not use `overwrite=true` to clear an existing project.
5. Read the repository's `AGENTS.md`, otherwise `CLAUDE.md`, then `README.md` and mandatory linked instructions completely before editing. Use a distinct branch/linked worktree under `.worktrees/` for concurrent work.
6. For substantial edits, use Server terminal Git and `github_authorize_local_git` when authenticated transport is required. Keep API and terminal credentials out of files, logs and chat.
7. Run mandated tests and Git hooks. Publish a validated branch with `github_push_local_git`, then create a PR if requested. Never change protected branches, overwrite other agents' work or merge without authorization.
8. Report branch, commit, checks actually run and any missing runtime verification.

The MCP guidance does not itself enforce canonical checkout paths; treat these checks as mandatory until the tool enforces them.
