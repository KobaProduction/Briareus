---
name: source-control-publishing
description: Briareus-specific GitHub and GitLab MCP workflow for canonical checkouts, account permissions and safe publishing.
---

# Briareus source-control MCP workflow

Use this skill with Briareus GitHub/GitLab Hands and their shared Server Hand.
It contains platform-specific operation rules, not universal Git training.
Generic Git, commit, review and multi-agent rules belong to the independently
installed AI Agent Workflow plugin; do not require opening its repository.
If that plugin is absent, follow the target repository's mandatory sources,
the selected provider's tool contracts and the operator's explicit policy.

1. Verify the selected account and its actual repository/project access before
   using provider tools. Do not confuse a visible tool with authorization.
2. Reuse the canonical checkout at /workspace/projects/<repository-name-lowercase>.
   Inspect its remote, worktree state, active branch, and other linked worktrees
   before cloning. Never create a duplicate /projects/<task>/repo checkout.
3. Read the target repository's AGENTS.md, or CLAUDE.md, then README.md
   and owner documents if the higher-priority map is absent. Stop affected work
   if required sources cannot be read completely.
4. Resolve the target integration branch from the repository and user policy.
   It is not necessarily main (Briareus V1 uses v1). Do not silently
   change it or override branch protections, required reviews or credentials.
5. For local Git changes, use the shared Server checkout and the corresponding
   provider's authorized local-Git credential helper. Never print or persist
   credentials in repository files or tool results.
6. Prefer a validated non-force, fast-forward direct push when the selected
   account and branch rules permit it. Use PR/MR only when explicitly requested
   or a verified protection/review requirement requires one; if the user forbids
   PR/MR, report a genuine block instead of opening one.
7. Before publishing, run required repository checks and Git hooks and confirm
   the remote HEAD has not unexpectedly advanced. Report the actual destination,
   status and remaining risks. Do not treat a queued action as completion.

This skill does not grant provider API permissions or override user approval.
