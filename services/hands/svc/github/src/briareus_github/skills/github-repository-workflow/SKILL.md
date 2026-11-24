---
name: github-repository-workflow
description: Use Briareus GitHub MCP and Server Hand for repository discovery, permissions, safe checkout and publishing.
---

# Briareus GitHub Hand

Read skill://source-control-publishing/SKILL.md for the Briareus-specific
checkout and publishing contract. The standalone AI Agent Workflow plugin
provides optional universal Git guidance; no external Git fetch or Docker
skill synchronization is required for this Hand to operate.

1. Select the GitHub account and verify its effective repository capabilities,
   branch restrictions, and writer/reviewer identities.
2. Reuse the canonical Server checkout when its remote matches the requested
   repository. Clone only if absent, with destination
   projects/<repository-name-lowercase>, mode=git, overwrite=false.
3. For local source edits, use the Server terminal and the approved
   authorize_local_git helper for the existing checkout. Do not
   expose token material or create duplicate workspaces.
4. Verify the required target branch. Prefer validated direct push when allowed;
   do not create a PR unless the operator requests it or protection requires it.
5. Follow repository-specific rules, actual tool permissions and mandatory
   local checks. User authorization and protections take precedence.

This Skill and the read_project_workflow fallback are shipped with Briareus,
not downloaded from another repository at image-build time.
