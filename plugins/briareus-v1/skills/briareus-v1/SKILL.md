---
name: briareus-v1
description: "Work on the Briareus V1 platform, MCP Hands, Gateway, Control Panel, Coolify, runtime, Git policies, and tests."
---

# Briareus V1 project workflows

This skill contains Briareus-specific project context; it does not replace
universal engineering Skills, grant MCP permissions or describe the separate V2 architecture.

Before Briareus source work, read references/AGENTS.md, references/README.md and
references/docs/core/runtime.md in full. Then route to the relevant owner documentation:

- MCP server/files/terminal: references/docs/hands/server.md
- GitHub/GitLab: references/docs/hands/source-control.md
- Analysis, browser, telemetry: references/docs/hands/README.md
- Gateway, panel, dependencies: references/docs/services/README.md
- Coolify/build/config: references/docs/operations/README.md
- Testing: references/docs/operations/testing.md
- Git/worktrees: references/docs/operations/git-and-worktrees.md

The service catalogue is references/deploy/services.json. Each selected service's
README is under references/services. Read every selected mandatory owner document
completely. Check current Git branch, live resources and permissions before
mutations. Preserve external secrets, persistent volumes and the V1/V2 boundary;
no changes to stopped services without approval. Other task-specific engineering
workflows belong to the separate AI Agent Workflow plugin.
