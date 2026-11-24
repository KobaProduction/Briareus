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

## Local publishing guidance

This Hand publishes the shared Briareus-owned `source-control-publishing` Skill
alongside its provider-specific Skill. `read_project_workflow` combines both
texts for clients without Skills support. Actual repository branch policy,
permission checks, canonical Server checkout rules and operator requirements
remain authoritative.

No external workflow repository or build-time Markdown download is required.
Universal Git and multi-agent engineering Skills, when desired, are provided
by the independently installed AI Agent Workflow marketplace.

## Provider capability parity

GitLab exposes native merge request approvals and reviewer assignment, change
requests, draft/ready state, discussions (including pinned diff positions),
note lifecycle, rebase, pipelines and jobs, commit statuses, job artifacts,
repository tags, and text/binary file access.

The Hand uses the shared repository-file/tag interfaces, binary codecs,
download transport and local-first middleware in `shared/git`, alongside
GitHub. Existing GitLab tool parameters are retained. The common tag tools
accept `repository` (a project ID or namespace path); file operations accept
`encoding="utf-8"` or `encoding="base64"`. Artifact downloads return the
exact bytes as base64 with their size and SHA-256.

Approvals, approval rules and GraphQL review actions depend on instance
version, tier and account permissions. Rebase checks the expected source HEAD
before queueing, but GitLab does not make that precheck atomic. Poll the merge
request for completion. Native approval rules and merge status remain
authoritative.

Use the canonical local checkout and authenticated Git transport for branch
rename, fast-forward, reset, history rewrite and cross-ref file copies.
GitLab push supports an explicit expected remote SHA for force-with-lease.
The Hand does not emulate GitHub-specific ref APIs using unsafe multi-step
remote mutations.
