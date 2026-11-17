# Analyzer G — Briareus project/session and behavior tools

**Owner:** [V1 analysis Hands](../analysis.md), [Analyzer G service](../../../services/hands/analysis-g/README.md).
This is the **Briareus public facade**, not a direct command guide for its
underlying external engine. Generic reverse-engineering evidence and naming
methodology belongs exclusively to the independent AI Agent Workflow
`reverse-analysis` Skill.

## Project and program are separate from worker state

1. Discover the saved project with `list_projects`; identify its stable
   `project_id`. Confirm target bytes, version, mapping and selected program.
   `open_project(project_id)` attaches an isolated project session.
2. Inspect `project_session_info(project_id)` and `list_active_programs(project_id)`
   before modifying analysis. If multiple programs are active, explicitly
   select a `program` on every subsequent operation; omitting it may silently
   target the wrong program.
3. If a saved program is not open, inspect project files and use
   `open_project_program(project_id, path)` for the existing artifact.
   Losing a worker handle is **not** evidence that the saved program is gone.
   Reimport only on actual missing/corrupt persistent program evidence.
4. Use `list_tool_groups`, then `load_tool_group(group)` **only** for the
   required capability; tool categories may be lazy-loaded. Discover schemas
   at call time. Do not invent a tool when it is not loaded or available.

## Analyzer G action nodes, high and low views

The facade calls code units **action nodes**: action address/name,
inbound/outbound action links, action route map, action metadata and
high-/low-level views. These are *not* generic names for data, devices,
external processes, or arbitrary objects. Preserve exact program identities.

- `analysis_status(project_id, program)` shows current analysis state.
- `list_actions(project_id, program)` lists action nodes. The published
  schema has **no offset/limit pagination**. Do not pass legacy pagination
  arguments: [issue #240](https://github.com/KobaProduction/Briareus/issues/240).
- `get_high_level_behavior_view` accepts one `action` or multiple
  comma-separated `actions` and can apply an independent timeout per action
  during a batch. Record failures per action rather than inferring success.
- `get_low_level_action_view` and `get_action_ir` support bounded checks
  of ambiguous instructions/IR, then return to high-level evidence.
- `get_inbound_action_links`, `get_outbound_action_links` and
  `get_action_route_map` locate control dependencies. Scope by project
  and program; use space-qualified addresses when multiple spaces exist.
- Before semantic mutations, inspect current action identity/metadata;
  update evidence-backed names/types/comments using actual exposed tools,
  save the project and **read back** the materialized result.

Do not bypass Analyzer G by calling the underlying native adapter merely
to work around an error or an unloaded group. The external analysis engine
and its database are **not** the shared Server workspace.

## Worker/session errors and safety blocks

An idle session released or worker moved does not change canonical
`project_id`. Reacquire the session and program from the persistent project;
do not spin up duplicate imports. `recover_worker` can cancel in-flight
requests and restart a worker — this is **not** an ordinary retry mechanism.
`set_worker_max_heap_mb` changes persistent JVM Xmx and may kill the worker;
it is not a container RSS/cgroup limit. Confirm authorization, impact and
saved state before using lifecycle mutations.

[Issue #378](https://github.com/KobaProduction/Briareus/issues/378)
records a *pre-tool policy block* of `open_project` on an existing project.
The backend was **not reached**; this proves no target-program failure.
Record sanitized operation and exact rejection, check policy/authority,
do not repeat blindly or switch tools to evade the block.

For repeatable script execution and long jobs, read
[Analyzer G scripting/job contract](analyzer-g-scripting.md)
**before** launching a script.

**Acceptance:** original project remains authoritative, exact program
is selected, requested behavior evidence is saved/read back, and no
unrelated worker, program or provider state is changed.
