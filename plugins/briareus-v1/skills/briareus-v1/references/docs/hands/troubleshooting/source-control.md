# GitHub/GitLab MCP — identity, branch and publication errors

**Owners:** [source-control Hands](../source-control.md) and
[canonical worktree/checkout rules](../../operations/git-and-worktrees.md).
Universal Git methods are in the independent AI Agent Workflow
`git-workflow` Skill; this guide only describes **Briareus integration
behavior** and known mistakes.

## Provider MCP works, but local Git push fails

A named GitHub/GitLab account in Control Panel and the Server terminal Git
credential are **different authorization surfaces**. A visible MCP tool
does not prove write authority, and terminal Git does not silently inherit
MCP credentials.

**Diagnose:** verify exact selected provider account, repository, remote,
branch, effective provider permissions, and whether the canonical checkout
already exists. When needed use the corresponding Briareus
`authorize_local_git` helper for the **existing** checkout. Do not
paste tokens into commands, remotes, logs or files. An auth/network failure
is not proof that a PR/MR is required.

## Branch name is mistaken for a policy

[Issue #370](https://github.com/KobaProduction/Briareus/issues/370)
recorded a Briareus provider-layer `main/master` reserved-branch block
even where remote GitHub protection was disabled. This *historical report*
is not evidence of the current deployed policy.

Check actual remote protection/rulesets, **then** the Briareus provider's
effective policy and the selected account. Respect the project's real
integration branch; Briareus V1 uses `v1`, not an assumed `main`.
An unauthorized source mutation must not be retried through an unrelated
account or transport to bypass enforcement. Current local-first policy
requirements are tracked in
[issue #294](https://github.com/KobaProduction/Briareus/issues/294).

## Unexpected PR/MR or deletion of the source branch

[Issue #428](https://github.com/KobaProduction/Briareus/issues/428)
documents a requirement for an explicit source-branch retention choice in
PR/MR workflows, and gaps in some older provider APIs. Before creating
or merging a PR/MR, obtain the operator's exact **keep/delete** choice;
do not rely on an omitted flag or repository default. If current tooling
cannot guarantee the choice, stop the affected merge/cleanup and report it.
Only consider deleting an actually merged and correctly identified source
branch; verify head ref/SHA and guard against recreation, forks, protected
branches and races. Ordinary push does not request branch deletion.

For an authorized unprotected integration branch, a validated non-force,
fast-forward direct push may be appropriate. Review requirements and
explicit user instructions override the default. Never create a PR/MR
only because the command failed to connect.

## Duplicate checkout from a Git error

Do not solve an auth/branch failure by creating `projects/<task>/repo`
or another clone. Use the [one checkout authority](../../operations/git-and-worktrees.md),
inspect the existing remote and unpublished work, and stop on collisions.

**Completion:** verified account, target remote/branch and actual server
policy; published expected SHA or reported the exact blocker. No credentials
were exposed and no branch was silently removed.
