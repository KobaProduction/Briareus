# Analyzer G — scripted analysis and job safety

**Owner:** [Analyzer G](analyzer-g.md), [Briareus Server/jobs](../server.md).
This document contains **Briareus API-specific** operations. General
reasons to automate, proof levels and semantic naming are owned by the
standalone AI Agent Workflow `reverse-analysis` Skill.

## Critical: do not launch an unmanaged synchronous script

[Issue #388](https://github.com/KobaProduction/Briareus/issues/388)
records a direct `run_analysis_script_inline` call timing out while
the analysis worker still had an in-flight operation. No durable
`job_id` was returned, so repeating the call risked duplicate heavy work.

The **required target contract** is native `start_script_job` with
status/output/cancel by job identity, but confirm availability in the
actual deployed tool list: it was not present in the inspected public
tool surface. Do **not** invent that API or call synchronous methods
and claim they provided a managed job.

For longer scripts, the documented interim mechanism is an authorized
**Server Terminal persistent job** that makes one real Analyzer G MCP
request. Do not create an ad-hoc local Python wrapper or a second analysis
database just because an agent needs progress. Only use a project-approved
runner capable of invoking the existing MCP contract and preserving logs.
If unavailable, stop and report the missing capability.

## Exact public tools and permissions

Analyzer G exposes `run_analysis_script_inline(project_id, code, program,
dry_run, args)` and `run_analysis_script(project_id, script_name, program,
timeout_seconds, capture_output, dry_run, args)`. Both are project-scoped
and gated by its analysis scripting setting; **tool presence alone does not
permit direct execution outside a tracked job**. Follow #388 and the
operator's script-execution policy. A dry-run flag does not prove that
client/server transport is asynchronous or that execution can be cancelled.

Before any managed script operation:
- Verify the canonical `project_id`, exact `program`, actual open-session
  state, selected action scope, requested source and executable permissions.
- Read `get_storage_info(project_id)` for the configured project and
  script roots. The native engine's persistent script store, inline
  compilation cache and Briareus Server workspace are not the same.
- Prefer a provider-supported, authorized script install/upload if it
  exists. A successful inline run is **not** a persistent installation.
  Do not manually write files into engine internals or derive paths from
  project names.
- Before using an existing registered script, compare reviewed source
  identity; do not overwrite another source with the same name.
  A headless `list_scripts` response may not inventory every deployed
  script; successful execution of an approved stored path and verified
  source readback are stronger proof.

## Job execution, result and recovery

For an actual supported tracked job, retain `job_id`, selected
project/program, script version, inner/outer budgets and expected output.
Inspect `job_status` and incremental `job_read(cursor)` before retrying.
The Terminal process exiting 0 does not imply the inner Analyzer G
operation succeeded: check the MCP result, script output, coverage
and saved project state.

A client timeout is **not** proof that the script stopped. Check
`project_session_info` and the managed job first; do not pile another
run onto a worker with an in-flight operation. Worker recovery is an
explicit disruptive decision, not a substitute for deduplication or
a normal cancel. Preserve unsaved analysis and get operator approval.

Scripts should normally be read-only; modifications require narrow
authorization and save/readback. Record inspected functions/actions,
new confirmed edges, unresolved contradictions and actual persistence,
not a made-up percentage inferred from elapsed execution time.

**Acceptance:** traceable job identity exists, result and logs are
retrievable without replay, the saved canonical project remains intact
and the analyzer's actual success is confirmed independently of process
exit. If managed execution is unavailable, report that limit clearly.
