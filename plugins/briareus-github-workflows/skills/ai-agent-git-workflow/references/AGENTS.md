# AGENTS.md

Mandatory workspace map for agents working in this repository.

## Important

Do **not** reread `prompts/accounts/universal.md` or a project prompt as a runtime prerequisite.

Those are source templates for account/project configuration and are assumed to be injected by the harness already.

Read them only when the task is to design, audit or update prompts.

## Start

Use this map and the injected Account/Project prompts. Select only the
relevant task skill(s) below; load further contracts when the task
requires them. `skills/README.md` is an optional discovery map,
not an additional mandatory startup step.

Read selected mandatory sources completely through the Project's designated
authority. If a required source is unavailable or incomplete, do not perform
actions that depend on it; follow the injected Account/Project rules.
Do not reread account/project prompt templates merely to start work.

For workflow-library changes, consult the owning audit or architecture
source when relevant. For every skill creation, edit, split, merge or review,
load `skills/skill-authoring.md` first. For governed progress reports, use
`docs/REPORTING_PROTOCOL.md`. Avoid loading the whole library.

## Routing

Playbooks (decision/checklist guides, not additional runtime prompt layers):
- new service / repository setup → `playbook/new-project.md` (load when planning a new project)


Task skills:
- multi-agent coordination / PDCA / peer communication → `skills/orchestration/README.md`
- implementation/refactoring/backend/Python/PostgreSQL → `skills/software-engineering/README.md`
- frontend/Vue/TypeScript/FSD/UI/tables → `skills/frontend-engineering/README.md`
- software test design, run profiles and suite audits → `skills/software-testing/README.md`
- project bootstrap / toolchain / lint, types, hooks and CI setup → `skills/project-bootstrap.md`
- writing/editing/splitting/reviewing skills → `skills/skill-authoring.md` (mandatory)
- Git / Issues / branches / commits / PR-MR / Git-backed coordination → `skills/git-workflow.md`
- independent review → `skills/code-review.md`
- interface/UX design review and acceptance → `skills/interface-design-review.md`
- scientific flowcharts, Draw.io/SVG diagrams, measured/calculated plots and spreadsheet-backed charts → `skills/scientific-visualization.md`
- shell/SSH/UART/PowerShell/WSL/remote execution → `skills/terminal-operations.md`
- any task that emits human-operated commands → `skills/terminal-operations.md` (mandatory)
- service/deployment/infrastructure operations → `skills/services-deployment/README.md`
- remote browser sessions / Chrome tabs / DevTools / extension permissions → `skills/remote-browser-session.md`
- reusable service deployment examples/presets → `examples/services/README.md` after loading the relevant services-deployment skill
- program analysis (EXE, BIOS/UEFI, firmware, libraries, drivers), behavior tracing and Ghidra/Analysis → `skills/reverse-analysis.md`
- OpenIPC migration/porting/contribution → `skills/openipc-porting.md`
- context-efficient documentation/bootstrap/multi-agent workflow design → `skills/context-engineering.md`
- chat/workflow/prompt audit → `skills/workflow-audit.md`
- registrar/domain procurement, long-term cost, transfers and DNS continuity → `skills/domain-acquisition.md`

## GitHub writer/reviewer identity contract

When both GitHub App identities are available:
- `koba-ai-agent` is the writer/Implementer identity. It may create working branches, commits, issues and pull requests, update its PR branch, and respond to review findings.
- `koba-ai-reviewer` is the independent Reviewer identity. It reads the proposed diff and current authority, submits review state, and is the only identity that merges pull requests into reserved/default branches.
- For PR-governed changes the writer never merges its own PR; the reviewer does not edit its implementation, and requested changes return to the writer.
- Direct push to an unprotected default branch is permitted only when Project policy and actual tool permissions allow it. Tool-reserved branches, required reviews and protected branches use `writer branch -> PR -> reviewer review -> reviewer merge`. Do not bypass tool restrictions through another transport.
- **AI Agent Workflow-specific permission:** when its `main` is unprotected and the active GitHub identity has write access, publish validated commits **directly to `main` without a PR**. If protection or a required review is introduced, use the existing PR route. This does not alter the general Git skill or other repositories.
- Account aliases are stable selectors; concrete App IDs, installation IDs and credentials remain infrastructure state and do not belong in this repository.

## Rules

- Keep this repository project-neutral.
- Do not store project IPs, hostnames, GPIO maps, active SHAs or machine-specific paths.
- Do not store credentials/tokens/private keys.
- Put task-specific rules in skills, not account prompt.
- Put environment values in local context, not universal prompts.
- Prefer editing an existing rule over adding a duplicate.
- Significant changes require an independent Reviewer pass.
- Generalize a lesson here only when it is reusable beyond one project.

## Depth

Preferred hierarchy:

`account → project → skill`

A skill may contain a small internal map, but avoid recursive prompt trees.
