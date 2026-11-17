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

## Shared publishing policy

This Hand reuses one published `source-control-publishing` skill from
`shared/hand_runtime/src/briareus_hand_runtime/skills/`;
that shared skill is listed alongside the provider-specific skill via MCP.
The fallback `read_project_workflow` tool includes both skill texts.
The publication default is a validated direct push to the authorized main branch.
Only a confirmed branch-protection/review requirement or explicit request
triggers PR/MR fallback, unless the user forbids creating one.

## Upstream skill sync

At image build, Git and orchestration modules are downloaded from
https://github.com/ArthurKoba/ai-agent-workflow at one resolved commit into
the shared ai-agent-git-workflow skill. GitHub and GitLab use the same
synchronization implementation. For clients without MCP Skills support,
read_workflow_reference(bundle=git, path=skills/git-workflow.md) retrieves
the packaged source. SOURCE.json records the upstream commit and file digests.
Upstream edits require a new image build and deployment to become active.
