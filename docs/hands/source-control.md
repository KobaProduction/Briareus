# GitHub and GitLab Hands

**Catalog:** `github`, `gitlab`. **Sources:** [GitHub](../../services/hands/svc/github/README.md), [GitLab](../../services/hands/svc/gitlab/README.md).

The source-control providers expose independent MCP surfaces at `/svc/github/mcp` and `/svc/gitlab/mcp`. Named accounts and encrypted credentials are owned by Control Panel API; Hands request only the explicitly selected account and enforce provider permissions at invocation time. A tool's presence or an account's declared capabilities does not grant permission.

For substantial source work, use the existing canonical checkout with local Git and the authenticated provider credential helper, instead of creating a new clone per task. Other agents use linked worktrees with their own branches. Repository-specific protections and GitHub/GitLab authorization are authoritative; do not assume an ordinary local credential can bypass them.

Provider-specific behavior and tests live with each Hand. [GitHub history and branch-operation contracts](../github-history-surface.md), [GitHub Actions](../github-actions.md), and [workspace policy](../operations/git-and-worktrees.md) provide related procedures. Runtime Git authentication must not be stored in documentation or logs.

## MCP-native workflow skills

Both providers require reading [ArthurKoba/ai-agent-workflow](https://github.com/ArthurKoba/ai-agent-workflow) via its
[`AGENTS.md`](https://github.com/ArthurKoba/ai-agent-workflow/blob/main/AGENTS.md) map and
[`skills/git-workflow.md`](https://github.com/ArthurKoba/ai-agent-workflow/blob/main/skills/git-workflow.md)
before Git operations. The shared skill routes commit, publication and
multi-agent tasks to their focused mandatory sources; it does not copy the
external library or override project permissions.

GitHub and GitLab each bundle a provider-specific `SKILL.md` and
share the one `source-control-publishing` skill, implemented in
`shared/hand_runtime/src/briareus_hand_runtime/skills/`. Both Hands
publish it through MCP Resources and the experimental SEP-2640 extension
(`io.modelcontextprotocol/skills`), with `skills/list`/`skills/get`.
The shared policy directs agents to push validated changes to main when permitted,
and to create PR/MR only when that push is confirmed blocked or review is
explicitly required. The repository's designated integration branch and an
explicit user ban on PR/MR creation take precedence.

The Server Hand bundles its own workspace workflow. All three also expose
`read_project_workflow` (model-callable tool) and `project_workflow`
(client-selectable prompt) for clients that cannot negotiate Skills.

The client **must support Skills-over-MCP** for automatic discovery.
Refreshing a ChatGPT MCP connection may refresh tools but does not by itself
prove ChatGPT will install or activate skills from the extension. The ordinary
workflow tool remains available. No Gateway behavior is changed by this
feature.

For MCP `serverInfo.version`, the three Hands use Coolify's
`SOURCE_COMMIT` (passed explicitly in their Compose environment), formatted
as `git-<sha-prefix>`. If absent, they publish a deterministic packaged-source
fingerprint beginning `src-`; they never claim an unknown commit was
verified. A new **deployed** commit changes metadata only once the Hand
container is replaced; a Git commit alone does not update a running process.

## Build-synchronized upstream references

GitHub and GitLab also publish the build-time ai-agent-git-workflow skill from
https://github.com/ArthurKoba/ai-agent-workflow . A source SHA and per-file
hashes are included in each image; the selected reference modules are
retrievable with read_workflow_reference(bundle=git, path=...). Upstream changes
become active after a new image build and deployment; they do not by
themselves trigger Briareus builds.
