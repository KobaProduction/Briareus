# Briareus V1 project plugin

The Briareus repository maintains its own plugin marketplace at
[marketplace.json](../.agents/plugins/marketplace.json).

Import https://github.com/KobaProduction/Briareus with Git ref v1 and install
the single **Briareus V1** package. This package contains exactly one
project-specific Skill and locally bundled reference documents about V1 service
ownership, Gateway, Control Panel, MCP Hands, source policy, Coolify and tests.
It includes the full 15-service catalogue and the README for each service.
It does not include universal engineering methods or the AI Agent Workflow
library. V2 is independently governed and not part of this package.

The former four Briareus provider-specific plugin packages are retired.
Existing Briareus MCP connections remain independent and should not be deleted.
The upstream AI Agent Workflow marketplace is a separate Git source, installed
only when generic engineering workflows are needed.

The native project Skill is generated automatically by a dedicated GitHub
Actions publisher after relevant V1 docs, AGENTS, or service-owner edits. It
validates and commits only native marketplace files, and does not use any
cross-repository secret or rebuild Docker.

Local contributors can regenerate the exact snapshot before committing via:

    python scripts/briareus_marketplace.py

The same command with --check verifies a deterministic package. CI regenerates
for validation, while the event-driven publisher commits the packaged result.
The installed ChatGPT/Codex client's refresh schedule remains a separate
product concern, not a guarantee of immediate Skill activation.
