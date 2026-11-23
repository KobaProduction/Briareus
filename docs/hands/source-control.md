# GitHub and GitLab Hands

**Catalog:** `github`, `gitlab`. **Sources:** [GitHub](../../services/hands/svc/github/README.md), [GitLab](../../services/hands/svc/gitlab/README.md).

The source-control providers expose independent MCP surfaces at `/svc/github/mcp` and `/svc/gitlab/mcp`. Named accounts and encrypted credentials are owned by Control Panel API; Hands request only the explicitly selected account and enforce provider permissions at invocation time. A tool's presence or an account's declared capabilities does not grant permission.

For substantial source work, use the existing canonical checkout with local Git and the authenticated provider credential helper, instead of creating a new clone per task. Other agents use linked worktrees with their own branches. Repository-specific protections and GitHub/GitLab authorization are authoritative; do not assume an ordinary local credential can bypass them.

Both provider Hands expose explicit repository/project creation tools. GitHub
`github_agent_create_repository(account_id, owner, name, private=True, auto_init=False)`
resolves the selected account owner installation (not an existing repository)
and requires upstream repository creation rights. GitLab
`create_project(account_id, name, path="", namespace="", visibility="private")`
uses the authenticated user by default or resolves an exact namespace first.
Both default to private visibility; callers must explicitly choose another
visibility, and inspect remote state before retrying ambiguous creation failures.
GitHub installations restricted to selected repositories may need the newly
created repository added to their installation selection before further writes.

Provider-specific behavior and tests live with each Hand. [GitHub history and branch-operation contracts](../github-history-surface.md), [GitHub Actions](../github-actions.md), and [workspace policy](../operations/git-and-worktrees.md) provide related procedures. Runtime Git authentication must not be stored in documentation or logs.

## MCP-native Briareus guidance

GitHub and GitLab bundle provider-specific Briareus Skills and share a local
`source-control-publishing` Skill in the Hand runtime. They are available
through MCP Resources and the experimental `io.modelcontextprotocol/skills`
extension (`skills/list` and `skills/get`), plus the `read_project_workflow`
tool and `project_workflow` prompt for clients without Skills support.
They do not fetch external workflow repositories or require a GitHub connection
to read their own instructions.

The shared Skill owns Briareus-specific canonical checkout, account and
publishing behavior. It resolves the actual integration branch (`v1` for
Briareus V1), local credential helpers and effective permissions; user
instructions and branch protections remain authoritative.

General Git, review and engineering methodology is maintained and distributed
independently through the AI Agent Workflow marketplace. It is optional for
operation of these MCP Hands and is not built into their Docker images.

`serverInfo.version` uses the deployed `SOURCE_COMMIT` when valid, otherwise a
deterministic local-source fingerprint. It does not include external workflow
revisions. A new source commit changes deployed metadata only after the Hand
image is replaced. A client must support the MCP Skills extension to discover
Skills automatically; a tool refresh alone does not prove native Skill import.
