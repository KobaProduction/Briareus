---
name: source-control-publishing
description: "Shared GitHub/GitLab publishing workflow: prefer direct push to main when authorized; use PR/MR only when direct push is blocked or review is requested."
---

# Shared source-control and publication policy

Follow this workflow in GitHub and GitLab Hands. The provider-specific skill describes account discovery and concrete tool names; this shared policy owns common checkout, validation and publication decisions.

1. Identify the requested repository, its canonical `/workspace/projects/<repository-name-lowercase>` checkout and its remote. Inspect existing Server workspaces, working-tree changes, branches and linked worktrees; reuse the checkout. Never create a dated or task-named duplicate or overwrite another agent's work.
2. Read the repository's mandatory instructions (`AGENTS.md`, otherwise `CLAUDE.md`, then `README.md` and referenced mandatory docs) before modifying files. Protect unrelated changes and use a separate linked worktree/branch if concurrent work requires isolation.
3. **Publication default: direct push to `main`**, not an automatic pull/merge request. Confirm `main` exists and is the intended integration branch, and that the selected account can push there. If the user or repository's explicit policy requires another integration branch (for example `v1`), respect that policy; never silently retarget it to `main`.
4. Run relevant checks, validate the outgoing revision and follow Git hooks. If the target branch has moved, fetch, inspect the differences and use a non-force fast-forward path. Never bypass branch protections, force-push to shared branches, or discard unpublished changes to make direct push succeed.
5. When direct push is authorized and permitted, **push the validated changes directly to the target branch**. Do not create a PR/MR just because a tool offers one, and do not treat a local working branch as proof that review is required.
6. **Fallback to PR/MR only when direct push is confirmed blocked** by branch protection, insufficient direct-push permission or an explicit review requirement, or when the user expressly requests a PR/MR. If the user expressly forbids PR/MR creation, stop and report the blocker instead. Do not treat generic network/authentication errors as evidence of branch protection.
7. For fallback, use the already validated working branch, push it if permitted and create exactly one necessary PR/MR targeting the authorized integration branch. Reuse an existing relevant open PR/MR rather than generating duplicates. Follow required reviewers/checks; do not merge unless authorized.
8. Report the actual destination branch, commit, direct-push result or the specific blocker and PR/MR URL, along with tests performed and remaining uncertainties.

These instructions do **not** override repository branch protections or provide server-side enforcement. Provider errors and remote permissions remain authoritative.
