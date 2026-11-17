# Reporting Protocol

Purpose: make progress reports concise, comparable across turns, and useful during long-running technical work.

This protocol defines how to interpret plain report requests versus full/detailed report requests. Project-specific vocabulary and evidence rules still apply.

## Report modes

### Plain / compact report

A plain report request means a **delta report**.

Typical triggers include:
- `report`, `status report`;
- `отчёт`, `короткий отчёт`, `упрощённый отчёт`;
- equivalent wording that asks for the current progress without explicitly asking for a full reconstruction of all known state.

The reference point is the **previous user-facing report for the same active goal**. Do not repeat facts, closed areas, unchanged progress, unchanged blockers or historical context that were already reported and did not materially change.

If there was no previous report for the active goal, use the task start or last explicit durable checkpoint as the baseline and treat the response as the first report.

A compact report follows this **fixed reading order**. Lead with what the work
produced; place the visibly emphasized progress/checklist block **fourth**, just
before the next direction. Do not start with percentages, SHA lists, test counts
or a status table.

1. **Key results** — the most important new implementation outcomes, decisions
   or discoveries since the previous report. Start immediately with substance;
   use at most a few short sentences/bullets and omit routine operational detail.
2. **Problems** — only new defects, contradictions, blockers or material
   limitations and their impact. If none arose, omit this section; do not add
   an empty "no problems" paragraph or repeat old blockers.
3. **Outcome / conclusion** — one concise sentence stating what the work
   achieved, whether the active objective is reached, and the actual validation
   level where necessary. Do not claim runtime or product acceptance from unit
   tests/builds.
4. **Progress** — a short, visually identifiable **Progress / Прогресс** block
   near the end, *after* the outcome. Show only directions that actually
   advanced, with the scoped **`before% → after%`** value when percentage
   tracking exists. Include the useful checklist delta, e.g. `4/6 → 5/6`,
   alongside the percentage, without pasting the whole checklist. A defensible
   changed overall metric may appear here. If no measurable change occurred,
   say so briefly instead of inventing a percentage.
5. **Next direction** — one immediate action or the next real decision boundary,
   as the **last section**. Do not append a recap or more progress below it.

Keep a plain report normally within **5–9 short lines**, expanding only for a
material blocker or an explicitly requested breakdown. Headings may be inline;
large tables, decorative cards, long checklists and repeated build/commit logs
are inappropriate by default. Optional sections must not force empty filler.

Percentage continuity remains mandatory when percentages are used: preserve the
same named scope/denominator across turns; report an approximate single value
if the previous numeric baseline is unavailable and say so briefly; never invent
precision, use a range or silently replace an established percentage with a
counter. An exact status/count may replace a percentage only where percentage
progress would be misleading or undefined, with a short explanation. These
metric rules govern the **fourth block**, not the report opening.

### Full / detailed report

A full report request means a **comprehensive current-state snapshot**.

Typical triggers include:
- `full report`, `detailed report`, `comprehensive report`;
- `полный отчёт`, `детализированный отчёт`, `подробный отчёт`;
- equivalent wording that explicitly asks for the whole current picture.

A full report may repeat previously reported information because its purpose is different. It should reconstruct the current state of the active objective across all meaningful directions.

A full report follows the same **results → problems → outcome → progress →
next directions** reading order, but may expand each part. Include, as relevant,
the goal and acceptance contract, accumulated confirmed results, current
blockers/uncertainties, validated artifacts and gates, remaining checklist
items, and priority next paths. Put the detailed scoped progress/checklist
breakdown **after the synthesis**, immediately before the next directions —
never at the start.

The same sticky-progress rules apply to full reports: if percentages are established or meaningfully estimable for an active direction/workstream, include them; exact counters may supplement them but do not silently replace them. Use state/counter-only reporting only when percentage progress is genuinely undefined or misleading, and say why. Never use min/max percentage ranges. Preserve validation-level distinctions; implementation proof, execution proof, board proof and integration proof are not interchangeable.

## Reports after context refresh

A request to re-read rules or refresh context does not itself request a full
report. Use the same results-first compact delta format unless the user asks
for a comprehensive snapshot. Reading rules is not implementation progress;
report only newly established decisions, fixes, contradictions or blockers.

## Progress metric discipline

### In-scope progress versus external dependencies

- Anchor each percentage to the **current task's artifact, declared
  deliverable and acceptance boundary** before computing it. For a
  single-version firmware reversal, the denominator covers behavior
  recoverable from that target, not unrequested research into other BIOS
  versions, EC internals, hardware tests, driver support or application
  development. Include an external dependency only when the active task
  explicitly owns and requires it.
- Report a complete in-scope deliverable as **100% of that named scope**
  when its acceptance evidence is closed, even when external behavior is
  unknown; record the external condition separately without penalizing
  the current progress. Conversely, completing one API or command must
  not be reported as 100% of a larger feature with other unfinished
  in-scope contracts.
- Do not keep an unjustified 95% or 98% because of unrelated external
  unknowns or an impression that implementation is never fully proven.
  Require traceable remaining gates or a defensible estimation basis.
  When an earlier percentage included out-of-scope obligations,
  explicitly **retire/rebaseline** it, explain the changed denominator
  and report the external work separately; do not show this metric
  correction as new technical recovery.

A report percentage is a communication metric, not objective truth by itself.

- Scope the percentage to a named direction or denominator.
- Display changed progress in the **fourth report block**, following results,
  problems and outcome, and before the final next direction.
- Reuse the same denominator/estimation basis across successive compact reports so `before -> after` remains meaningful.
- Exact `closed / total` counters are useful evidence and may accompany a percentage, but they do not automatically replace an established percentage metric.
- If the user or previous reports established percentage-based progress for the active workstream, preserve that format across subsequent reports unless the user changes it or the denominator becomes invalid.
- When no exact denominator exists but progress is still meaningfully estimable, use one scalar approximation and keep the estimation method stable.
- Never show a range merely to avoid choosing a usable scalar. If percentage progress is genuinely undefined or misleading, report a state/count transition and say why no percentage is shown.
- Do not revive an old percentage after its denominator was retired or redefined.

## Report checkpoint continuity

For long-running work, the previous report baseline must not depend only on fragile chat memory.

When the task already maintains durable Task Context, status, handoff or structured state, keep enough report-checkpoint information there to recover:
- the active goal;
- the last reported progress values/counters, including the active percentage denominator/estimation basis when percentages are in use;
- the last reported material findings;
- the next decision boundary at that report.

Do not create a second planning database only for reports. Reuse the project's existing durable task/state authority.

## Issues and project boards are current state, not execution logs

Keep user-facing reports in the conversation. An issue or project-board item is
an editable work checkpoint: goal, scope, acceptance criteria, current progress,
important decisions, next tasks and material blockers. Update the existing state
instead of appending a new report after every work session.

Keep concise technical findings when they help a reader understand or resume the
task: semantic names, register ranges/fields, behavior contracts, evidence level,
remaining unknowns and useful references. A logical object identity in the
canonical analysis is useful even when its storage is private; a private
filesystem path presented as a repository deliverable is not.

Do not copy chat reports, tool transcripts, step-by-step activity, script counts,
private script inventories, temporary files, worker/job identifiers, checksums or
backup/archive paths into an ordinary task issue. Do not imply that a file exists
in the repository merely because it exists in an analysis service. A dedicated
infrastructure incident or explicitly requested runbook may contain the minimal
operational detail required to diagnose its own task; do not copy that detail
back into the product issue.

Keep detailed traces, script sources and recovery locators in their owning
analysis/artifact/local-context surface. The task issue may identify the
canonical project and semantic objects, or link accessible evidence, without
mirroring its internal storage. Use the existing durable authority rather than
creating a second planning database. The report checkpoint is a compact set of
facts and metrics, not a copy of the last report.

When cleaning an existing issue, preserve unique conclusions, unresolved
contradictions, acceptance criteria and meaningful evidence references. Verify
that unique technical evidence survives in its owning surface before removing
it. Do not move the same execution log into a new issue comment and call that
cleanup. Keep historical decisions only where their history remains useful.

## Interaction semantics

- `report` by itself means: provide the report and stop there.
- `report and continue` means: provide the report, then continue the active work.
- `full/detailed report` by itself means: provide the comprehensive snapshot and stop there.
- If the user explicitly asks for another format or level of detail, that instruction overrides these defaults.

## Anti-patterns

Do not:
- lead a standard report with percentages, counters or a checklist before the actual results;
- move the progress block below the next direction or tack on a second conclusion after it;
- turn compact reports into long tables of commits, tests, files or historical status;
- omit percentages merely because an exact counter or state transition is also available when percentage reporting is already established or meaningfully estimable;
- silently switch a direction from percentage reporting to counters/status without explaining that the old denominator became invalid;
- repeat the same unchanged findings in every compact report;
- show every project area when only one or two changed;
- mix current progress with historical ranges;
- use `50-70%` style ranges in place of a usable scalar;
- silently change the denominator behind a `before -> after` comparison;
- claim completion merely because one direction reached 100%;
- omit the immediate next path when the goal remains open;
- continue technical work after a report-only request unless the user also asked to continue.
