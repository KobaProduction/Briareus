# Briareus V1 Github

Independent Github MCP hand. Accounts and authority come from the private Control Panel API; this service does not access the panel database directly.

Deploy this owner with `docker-compose.yaml` or the generated
`docker-compose.coolify.yaml`. Use the common environment Destination/network.

The Dockerfile installs this directory's frozen dependency lock and copies its
owned source plus explicitly consumed shared capability packages. The
Dockerfile-specific ignore file excludes all other repository content.

## MCP workflow guidance

The GitHub Hand includes
`src/briareus_github/skills/github-repository-workflow/SKILL.md`, registered
using FastMCP's experimental Skills extension. Clients supporting
`io.modelcontextprotocol/skills` can request `skills/list`, `skills/get` and
`skill://github-repository-workflow/SKILL.md`. Other clients can access the
same instructions via the `read_project_workflow` tool and `project_workflow`
prompt. The tool description and MCP server instructions also direct agents to
inspect existing Server checkouts before cloning.

Current GitHub checkout code still accepts noncanonical destinations: this
workflow is guidance, **not** a path enforcement boundary. Source policy changes
need separate validation and tests.

The MCP server version uses `git-<12 hex characters>` from the deployed
`SOURCE_COMMIT`, or a `src-<hash>` fingerprint in standalone environments.
This is independent of `pyproject.toml`'s package version.

## Local publishing guidance

This Hand publishes the shared Briareus-owned `source-control-publishing` Skill
alongside its provider-specific Skill. `read_project_workflow` combines both
texts for clients without Skills support. Actual repository branch policy,
permission checks, canonical Server checkout rules and operator requirements
remain authoritative.

No external workflow repository or build-time Markdown download is required.
Universal Git and multi-agent engineering Skills, when desired, are provided
by the independently installed AI Agent Workflow marketplace.

## Unified provider tools

Public tool names describe operations (`get_file`, `create_repository`,
`create_review`), not internal roles. Only one set of repository/PR/Actions
read tools is published. `account_id` selects the configured GitHub identity
and upstream GitHub permissions enforce access. The independent reviewer
account remains selectable without a duplicate MCP surface. The old
`github_agent_*` and `github_reviewer_*` tool names are not published.
