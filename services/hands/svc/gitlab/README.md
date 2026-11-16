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
