---
name: gitlab-repository-workflow
description: Use Briareus GitLab MCP and Server Hand for GitLab account access, canonical workspaces and controlled publication.
---

# Briareus GitLab Hand

Read skill://source-control-publishing/SKILL.md for Briareus-specific
checkout, authentication and publishing rules. Generic Git methods are
independently available in the AI Agent Workflow plugin when installed; the
GitLab MCP does not require it or fetch it when building.

1. Select the GitLab account and verify the target project/namespace and
   effective permissions. Stop on ambiguous repository name collisions.
2. Inspect the existing Server checkout and verify its remote before cloning.
   Use projects/<repository-name-lowercase>, mode=git, overwrite=false
   only when the canonical destination is free.
3. For local Git operations authenticate with the authorized
   authorize_local_git provider helper. Never disclose credentials.
4. Respect the actual integration branch and branch protection. Use a
   verified non-force direct push if permitted; open an MR only on a proven
   review requirement or explicit request.
5. Follow repository rules and relevant required test/hook checks. Do not
   assume a network/authentication error means an MR is necessary.

The server publishes this native Skill and read_project_workflow without
any dependence on the external AI Agent Workflow Git repository.
