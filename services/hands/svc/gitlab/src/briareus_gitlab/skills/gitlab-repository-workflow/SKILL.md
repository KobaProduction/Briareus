---
name: gitlab-repository-workflow
description: Use Briareus GitLab and Server MCP tools for repository discovery, checkout, edits and publishing. Consult shared source-control-publishing skill; direct push to main is preferred over MR where permitted.
---

# GitLab provider workflow

**First load and follow `skill://source-control-publishing/SKILL.md`.** It is the single source for canonical checkout and publishing rules. Prefer direct push to `main` when it is the authorized integration branch; create an MR only on confirmed direct-push blockage, explicit review requirements or an explicit user request.

1. Call `accounts`, `list_projects` and `project_status` for the selected GitLab account. Verify effective branch permissions; namespaces can contain projects with identical basenames, so stop on ambiguous canonical path collisions.
2. Use Briareus Server `workspace_list` and `terminal_exec` to inspect the canonical repository path. If absent, use `checkout_repository(account_id, project, destination="projects/<name-lowercase>", mode="git", overwrite=false)`. Do not use extra clone directories or nested `/repo` folders.
3. Use `authorize_local_git` for Server terminal Git authentication if needed; keep provider tokens out of source and logs.
4. Check the target branch and permissions; use authorized non-force fast-forward `push_local_git` or ordinary Server Git. Don't bypass protected branch restrictions or infer that an unrelated auth/network error requires an MR.
5. Only when shared policy requires review fallback, reuse the validated working branch and existing relevant merge request if any. Don't create MRs by default or merge without permission.
