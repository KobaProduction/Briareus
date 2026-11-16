# V2 documentation ownership and validation

## Canonical routing

Use [core](../core/README.md), [Infrastructure](../infrastructure/README.md), [Hands](../hands/README.md), [Shared](../shared/README.md) and [Operations](README.md) as the **entrypoint structure**. Detailed technical requirements remain in their existing `docs/architecture/`, `docs/hands/<module>/`, `docs/services/` and `docs/shared/` owner pages; a concise index does not replace their binding contracts.

Agent policy starts at [root AGENTS](../../AGENTS.md) and routes to the binding per-owner policy files. When relocating a policy, preserve its required invariants and update links, decision ownership and cross-references. Never let a historical development or legacy MCP Bridge roadmap override accepted V2 authority. V1 is maintained on a different branch.

## Evidence levels

1. **Target requirement:** a documented invariant or planned architecture. It does not assert source completion.
2. **Source/contract:** code, generated contracts, locks and static diagnostics from the specified checkout revision.
3. **Local runtime acceptance:** actually exercised behavior using explicit test authority and environment.
4. **Scoped deployed acceptance:** exact approved Development resource/commit, state, credentials, private RPC and real client operations.

Source or healthy containers cannot stand in for human login, Node Project isolation, Cedar grants, cross-transport replay safety or file transfer acceptance.

## Read-only documentation checks

For a documentation-only update, confirm the links, relative paths, owner index and branch-specific terminology against the tracked tree. Run doc-link/static checks without invoking the prohibited aggregate test suite during the source phase. Check all references under the new owner directories, including root AGENTS and other branch entrypoints.

**CI/quality contract (updated):** Pushes and PRs targeting V2 run static
source diagnostics and link checks. The old no-op CI job has been replaced
with actual lint/type/architecture selection and the tracked local hook
scripts. The separately authorized aggregate test phase runs only from
an explicit `workflow_dispatch` with `test_phase_authorized=true`.
A successful source-phase check is **not** a successful test-phase or deployed
acceptance. The optional source image build also requires that explicit gate.
The retired standalone Frontend/MVP Backend workflows and empty PR Policy
workflow were removed: the unified V2 CI now owns scoped frontend static checks
and the separately authorized aggregate frontend/backend tests and images.


The root agent rules mention historical local handoff paths under agents/ and coordination/; those are **not tracked** in the current checkout. Agents must not fabricate them or block unrelated valid work because they are absent. Use the existing tracked [coordination](AGENT_COORDINATION.md) and [workflow](implementation-workflow.md) and any explicit supplied local evidence.

Do not run or adjust Production resources while reviewing docs. The [strict Dev allowlist](BRIAREUS_DEV_ACCESS_SCOPE.md) also applies to read-only inspection.
