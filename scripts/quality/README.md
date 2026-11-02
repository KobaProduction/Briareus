# Local quality gates

## Source and test phases

Complete source work across all owners first. Source cleanup may delete tests
exclusive to removed or architecture-incompatible legacy contracts; preserve
coverage of applicable invariants and never delete tests to hide a current
defect. Do not write, adapt or run new/retained tests or fixtures during this
phase, including diagnostic tests and per-module acceptance suites. Scoped
static diagnostics and batched native checks are allowed. Only after all
source owners finish and the user separately authorizes the test phase may
new/retained test/fixture work and aggregate acceptance begin. Mandatory
hooks, quality thresholds and required checks remain enabled; do not repeat
tests/builds after each function or extraction.

## Source-phase diagnostics

Run static checks only, scoped to the relevant source ownership:

```sh
python scripts/quality_gate.py --checks lint
```

The default changed/untracked selection must be reviewed against the actual
owner scope. Whole-repository diagnostics are deliberate aggregate work,
not a loop after every extraction. Do not invoke test-bearing gate commands
as source-phase diagnostic checks.

## Authorized test-phase and commit/release checks

The test-bearing commands below apply only after explicit authorization of
the aggregate test phase. Existing mandatory Git hooks are not bypassed.
From the repository root:

```sh
python scripts/quality_gate.py                         # changed and untracked files
python scripts/quality_gate.py --staged                # proposed commit
python scripts/quality_gate.py --base origin/main      # committed range
python scripts/quality_gate.py --all                   # entire repository
python scripts/quality_gate.py --all --checks tests    # tests only
python scripts/install_quality_hooks.py               # enable tracked Git hooks
```

Requires Git, Python, uv and Bun. UI dependencies use their owning module's
frozen lock. The Python quality tool environment has its own frozen lock
in this directory; it does not replace runtime dependency locks.

## Local-first publication and CI batching

Agents may publish their owned task changes after completing local
validation; no separate approval is needed for every ordinary push or
approved Development deployment. Accumulate a coherent block locally and
run affected components, static diagnostics, behavior checks and tests
before publication. Source-first work and separately authorized aggregate
testing still apply: no untested source-phase push disguised as completion.

Hooks and required CI checks stay enabled. Pre-commit validates the exact
proposed changes; pre-push validates the actual outgoing revision/range and
its affected dependency consumers. Include only the intended owned changes,
not unrelated staged/unstaged peer work. Use a clean isolated validation
checkout when needed; never stash/reset peer edits or claim a different
revision was checked. Successful unchanged checks are not repeated without
a reason. Run the final full aggregate suite once at the completed test
boundary; do not use full-system tests as a loop during source extraction.

CI should run on coherent published blocks and relevant changed paths/
consumers, not on each local action or unrelated shared package. Do not
repeatedly dispatch identical all-image jobs or publish noisy tiny commits
to trigger CI. Change detection must include the actual dependency closure
without blanket shared paths that rebuild every service. This is a pipeline
requirement; documentation alone does not verify or modify CI configuration.
Actual configured hooks/protections remain binding until safely updated.

## Enforced policy

- Cognitive complexity: at most **15** in production, **30** in tests.
  Biome checks TypeScript/JavaScript and Vue scripts; complexipy checks Python.
  These are cognitive scores, not counts of assignments or lines.
- Ruff also limits production cyclomatic complexity to 15, branches to 15 and
  statements to 50. Test complexity is governed by the cognitive limit of 30.
- Python: strict mypy, explicit Any prohibited, missing annotations prohibited.
  `BRI001` rejects ordinary dictionary return annotations (including local
  aliases and forward annotations), literal/comprehension/constructor returns
  and local variables assigned such dictionaries. Use a dataclass, NamedTuple
  or model. AST checks complement mypy; they are not whole-program inference
  across arbitrary dynamic Python calls.
- UI: Biome recommended rules with errors for cognitive complexity, explicit
  any, banned types, non-null assertions and ts-ignore. Vue full parsing is
  explicitly enabled; upstream still marks this support experimental.
- Steiger validates FSD layers, cross-slice imports and public API boundaries,
  including Vue imports. Warnings fail the gate.
- TypeScript uses strict checking, including tests and indexed access checks.

Biome/Ruff inspect selected files. FSD and Vue types need the UI dependency graph.
Python types are checked in separate logical source owner groups to avoid merging
independent `application`/`domain`/`projects`/`common` packages. Infrastructure, Node, MCP
and shared-library owners stay separate even without a local `pyproject.toml`;
their nearest dependency project still supplies the Python interpreter. Existing nested dependency projects
retain their own source boundaries. Test/uv grouping is unchanged.
For an existing owner virtual environment, mypy runs in a temporary uv overlay
containing the exact quality-project mypy and official gRPC/Protobuf stub pins.
`--no-sync --no-env-file` preserves the owner's environment and avoids loading
application secrets. The overlay retains the owner SDK paths; its interpreter
also discovers the stub packages, without putting stub-only packages on
`MYPYPATH` or persisting a temporary interpreter path. Owners without a virtual
environment retain the quality interpreter and report missing dependencies.
The protobuf stubs target 7.35.1 while the current Node/Resources runtime pins
7.36.2. The used Message serialization, copy, field-presence, oneof and
unknown-field APIs have matching source contracts; this is not a claim that all
protobuf 7.36 APIs are covered. Runtime versions are not downgraded for typing.
Local test selection covers affected Python dependency owners and UI
behavior. Shared changes follow their actual direct/transitive consumers;
they do not by themselves require every unrelated owner suite. Deleted
files still select affected owners. The final full aggregate suite runs
once at the completed authorized test boundary. Existing mandatory hooks
remain binding; this policy does not change their implementation or permit
bypassing a required check. Qualify runner selection against actual inputs.
Root tests use the root project's frozen dependency environment, with pinned test-only
pytest/httpx/gRPC overlays. Test import paths include only existing bounded reuse
packages and the known source consumers exercised by owner or root integration tests;
the quality tool environment is not an application dependency environment.
Configuration changes select affected consumers; use the final aggregate
boundary for the full suite. Full mode includes existing legacy
source; no baseline exemptions hide existing violations.

Only generated protobuf Python and vendored provider JavaScript are excluded
from the corresponding static source checks. Service tests use their own frozen
uv projects; unavailable dependencies or unsupported host platforms fail visibly.
Each subprocess has a 180-second **quality-runner** budget, unrelated to MCP
execution limits. Complete diagnostics are saved to ignored `artifacts/quality/`.
No formatting or source auto-fixes are performed by the gate.

Pre-commit checks staged changes. Pre-push reads the actual outgoing refs;
new remote branches conservatively receive a full check. Hooks refuse tracked
unstaged changes or pushes of a revision other than the checked-out HEAD so
they cannot accidentally validate different source. They never stash, commit,
push, deploy, rebuild containers or reset data. CI workflows are unchanged.

Ruff receives explicit Git source paths in bounded batches, so a tracked module
inside a directory named `build/` is still checked. Every Python service/Hand
uses the root rules; no per-service copy or opt-in is required. Biome/FSD/Vue
cover the UI, which is currently the only JavaScript/TypeScript/Vue project.
These tools do not lint shell, Dockerfile, Compose/YAML or protobuf definitions.

The mandatory Clean Architecture/DDD source is linked from root `AGENTS.md`.
`ARCH001` checks direct imports from domain/application into frameworks and
outer adapters, including relative imports and legacy `*_domain.py` modules.
It complements port/invariant review; clean import paths alone do not prove
that a service has a correct domain model or transaction boundary.
