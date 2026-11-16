---
name: github-repository-workflow
description: Use Briareus GitHub and Server MCP tools for repository discovery, checkout, edits and publishing. Consult shared source-control-publishing skill; direct push to main is preferred over PR where permitted.
---

# GitHub provider workflow

**First load and follow `skill://source-control-publishing/SKILL.md`.** It is the single source for canonical checkout and publishing rules. In particular, prefer direct push to `main` when it is the authorized integration branch; create a PR only on confirmed direct-push blockage, explicit review requirements or an explicit user request.

1. Use `github_accounts`, `github_agent_list_repositories` and `github_agent_status` for the selected account. The GitHub app can see private repositories not visible in public browser searches; do not infer permissions from the repository name.
2. Use Briareus Server `workspace_list` and `terminal_exec` to inspect a matching canonical checkout. If absent, use `github_checkout_repository(account_id, repository, destination="projects/<name-lowercase>", mode="git", overwrite=false)`; never create `projects/<task>/repo`.
3. For local source edits use Server terminal Git. When remote authentication is needed, use `github_authorize_local_git` with the checkout's returned mount-relative destination. Do not copy credentials into chat, logs or source files.
4. Before publishing, verify the target branch and effective direct-push rights. Use ordinary Git via Server or `github_push_local_git` for an authorized fast-forward. Inspect remote updates; never rewrite shared history to avoid a protected-branch rejection.
5. Only if shared policy requires review fallback, use the existing working branch and GitHub pull-request tools. Reuse an existing relevant PR, do not create PRs routinely, and do not merge without authority.
