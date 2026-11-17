# Briareus V1 — native ChatGPT/Codex Skills marketplace

The GitHub repository root contains the supported Codex marketplace manifest at
[marketplace.json](../.agents/plugins/marketplace.json). In ChatGPT
**Add marketplace**, select **https://github.com/KobaProduction/Briareus**,
Git ref **v1**, and leave optional selective paths empty on the first import.

The marketplace contains four Skills packages: Server, GitHub, GitLab and
Coolify. These are **Skills-only** packages. They use separately connected
Briareus MCP applications for authorized tool calls and do not replace or
re-register those applications. Registered app IDs are account-specific and
must not be guessed or committed. Import the marketplace and install the desired
Skills packages once. A marketplace update is not the same as a live MCP tool
refresh, and the availability/cadence of automatic refresh is determined by the
specific ChatGPT/Codex installation.

The committed package snapshots include reviewed local Briareus Skills and
selected Markdown from ArthurKoba/ai-agent-workflow, pinned to an upstream
Git commit with SHA-256 provenance. Links to upstream files outside the
allowlist are rewritten to immutable GitHub commit URLs. The original source
hashes are retained separately in SOURCE.json.

After an upstream push, the existing GitHub notification sends a validated
repository_dispatch to Briareus. The receiver classifies affected workflow
documents, renders this marketplace from the immutable commit, verifies the
packages, and pushes changes only to v1. This updates native Skills without
rebuilding Docker images. Briareus Hand code and runtime deployments remain
separate concerns. Failed or unauthorized publication is visible as a failed
GitHub Actions job, not a silent confirmation of sync.

Manual verification is possible without downloading secrets or using Docker:
python scripts/briareus_marketplace.py --upstream-checkout PATH
--revision UPSTREAM_COMMIT --check (provide both options in one command).
