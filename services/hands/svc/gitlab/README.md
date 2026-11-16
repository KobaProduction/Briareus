# Briareus V1 Gitlab

Independent Gitlab MCP hand. Accounts and authority come from the private Control Panel API; this service does not access the panel database directly.

Deploy this owner with `docker-compose.yaml` or the generated
`docker-compose.coolify.yaml`. Use the common environment Destination/network.

The Dockerfile installs this directory's frozen dependency lock and copies its
owned source plus explicitly consumed shared capability packages. The
Dockerfile-specific ignore file excludes all other repository content.

## MCP workflow guidance

The GitLab Hand bundles
`src/briareus_gitlab/skills/gitlab-repository-workflow/SKILL.md` and exposes it
through the experimental MCP Skills extension, the
`skill://gitlab-repository-workflow/SKILL.md` resource, a `project_workflow`
prompt and the `read_project_workflow` read-only tool.

The workflow requires inspecting Server's canonical checkout first; nested
GitLab namespaces can have identical project basenames, so ambiguous collisions
require an explicit decision rather than a dated clone directory. The existing
checkout API does **not** yet enforce this behavior.

The advertised MCP version is `git-<12 hex characters>` derived from the
deployed `SOURCE_COMMIT`, or a deterministic `src-<hash>` fallback when it is
not available. The Python package version is independent.

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
the shared ai-agent-git-workflow skill. The same implementation is used for
GitHub. The fallback read_workflow_reference(bundle=git, path=...)
exposes a selected packaged document to clients without MCP Skills support.
Upstream changes become effective only after building and deploying a new image.
