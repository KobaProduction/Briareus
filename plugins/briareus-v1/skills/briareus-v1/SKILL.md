---
name: briareus-v1
description: "Use Briareus V1 MCP Hands or maintain the V1 platform and services."
---

# Briareus MCP usage and V1 platform

Use this Skill when working through any Briareus V1 MCP connection, even for
other projects. This is a Briareus-specific integration guide, not a universal
engineering workflow. AI Agent Workflow Skills, when installed, supply generic
Git, testing, development and deployment methods independently.

## For ordinary MCP tool use

1. Identify which Briareus Hand is relevant and inspect its available
   tools, descriptions, schemas, accounts, and effective permissions.
2. Load only the matching Hand's guidance. Prefer that Hand's local MCP
   Skill if supported, otherwise call its read_project_workflow tool.
   The source-specific reference maps in this package can also be read:
   - Server/files/terminal: references/docs/hands/server.md
   - GitHub and GitLab: references/docs/hands/source-control.md
   - Browser: references/docs/hands/browser.md
   - Analyzer/Ghidra/radare2: references/docs/hands/analysis.md
   - Coolify and SigNoz: references/docs/hands/telemetry.md
3. Read required guidance completely before dependent actions. Confirm
   credentials, working directory and actual remote/target state.
4. Respect user approval, tool boundaries, protected branches and secret
   handling. A visible tool does not grant its permission. A submitted
   deployment is not proof of a healthy resource.
5. Do not require a checkout of the Briareus repository or the independent
   AI Agent Workflow repository for ordinary MCP calls.

## For modifying Briareus V1 itself

Read references/AGENTS.md, references/README.md and
references/docs/core/runtime.md in full. Follow their owner routing.
Use references/deploy/services.json for the service catalogue, and the
selected reference under references/services/ for the service owner.
Operations and validation start from references/docs/operations/README.md;
Git and worktrees from references/docs/operations/git-and-worktrees.md.
Verify the active v1 branch and distinct V2 policies before making changes.

The project Skill and server-native Hand Skills are complementary; the
marketplace does not install or grant MCP connections. Universal engineering
Skills remain in their own AI Agent Workflow marketplace.
