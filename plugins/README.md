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

Generate this bundle after changing an authoritative Briareus owner document:

    python scripts/briareus_marketplace.py

Run the same command with --check to verify the repository has an up-to-date
snapshot. The test suite checks this invariant. GitHub marketplace synchronization
is handled by the ChatGPT/Codex client according to its supported schedule; no
cross-repository notification or Docker rebuild is needed for native Skills.
