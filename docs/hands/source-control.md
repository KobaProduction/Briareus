# GitHub and GitLab Hands

**Catalog:** `github`, `gitlab`. **Sources:** [GitHub](../../services/hands/svc/github/README.md), [GitLab](../../services/hands/svc/gitlab/README.md).

The source-control providers expose independent MCP surfaces at `/svc/github/mcp` and `/svc/gitlab/mcp`. Named accounts and encrypted credentials are owned by Control Panel API; Hands request only the explicitly selected account and enforce provider permissions at invocation time. A tool's presence or an account's declared capabilities does not grant permission.

For substantial source work, use the existing canonical checkout with local Git and the authenticated provider credential helper, instead of creating a new clone per task. Other agents use linked worktrees with their own branches. Repository-specific protections and GitHub/GitLab authorization are authoritative; do not assume an ordinary local credential can bypass them.

Provider-specific behavior and tests live with each Hand. [GitHub history and branch-operation contracts](../github-history-surface.md), [GitHub Actions](../github-actions.md), and [workspace policy](../operations/git-and-worktrees.md) provide related procedures. Runtime Git authentication must not be stored in documentation or logs.
