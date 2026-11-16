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
