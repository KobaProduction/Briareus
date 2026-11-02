import {
  type ApprovalAction,
  type ApprovalRecord,
  approvalStillCurrentForActor,
} from "@/entities/approval";
import type {
  ApprovalCommandContext,
  ApprovalCommandOptions,
  ApprovalResolution,
  CurrentApprovalResult,
} from "./contracts";
import { reconcileApprovalDecision, terminalApprovalDecision } from "./reconcile-decision";

export type { ApprovalCommandContext, CurrentApprovalResult } from "./contracts";

interface ApprovalActor {
  projectId: string;
  actorId: string;
}
type PreparedDecision = { kind: "prepared"; fresh: ApprovalRecord };
function currentContext(
  options: ApprovalCommandOptions,
  actor: ApprovalActor | null,
): ApprovalCommandContext | null {
  if (!actor || options.signal.aborted) return null;
  const value = options.context();
  if (!value || value.projectId !== actor.projectId || value.actorId !== actor.actorId) return null;
  return value.canApprove && Date.parse(value.proofExpiresAt) > Date.now() ? value : null;
}
async function prepareDecision(
  selected: ApprovalRecord,
  action: ApprovalAction,
  actor: ApprovalActor,
  options: ApprovalCommandOptions,
  current: () => ApprovalCommandContext | null,
  cancelled: () => CurrentApprovalResult,
): Promise<PreparedDecision | CurrentApprovalResult> {
  const verdict = await options.verify(options.signal),
    context = current();
  if (!context) return cancelled();
  if (verdict !== "authorized") return { kind: verdict };
  if (!approvalStillCurrentForActor(selected, context.rows, action, actor.projectId, actor.actorId))
    return { kind: "conflict", items: [...context.rows] };
  const before = await options.port.read(actor.projectId, options.signal);
  if (!current()) return cancelled();
  if (before.kind !== "ready")
    return { kind: before.kind === "conflict" ? "unavailable" : before.kind };
  if (!approvalStillCurrentForActor(selected, before.items, action, actor.projectId, actor.actorId))
    return { kind: "conflict", items: before.items };
  const fresh = before.items.find((row) => row.id === selected.id);
  return fresh ? { kind: "prepared", fresh } : { kind: "conflict", items: before.items };
}
async function reconcileDecision(
  decision: ApprovalResolution,
  selected: ApprovalRecord,
  actor: ApprovalActor,
  options: ApprovalCommandOptions,
  current: () => ApprovalCommandContext | null,
  cancelled: () => CurrentApprovalResult,
): Promise<CurrentApprovalResult> {
  const terminal = terminalApprovalDecision(decision, actor.actorId);
  if (terminal) return terminal;
  const after = await options.port.read(actor.projectId, options.signal);
  if (!current()) return cancelled();
  if (after.kind !== "ready") return { kind: "uncertain" };
  return reconcileApprovalDecision(decision, selected, after.items, actor.actorId);
}
function failedDecision(writeIssued: boolean, signal: AbortSignal): CurrentApprovalResult {
  if (writeIssued) return { kind: "uncertain" };
  return { kind: signal.aborted ? "cancelled" : "unavailable" };
}
/** Fresh owner proof -> exact revision -> one decision -> current owner evidence.
 * Captured actor/Project identity cannot change when the proof object is renewed.
 */
export async function resolveCurrentApproval(
  selected: ApprovalRecord,
  action: ApprovalAction,
  options: ApprovalCommandOptions,
): Promise<CurrentApprovalResult> {
  const initial = options.context(),
    actor = initial ? { projectId: initial.projectId, actorId: initial.actorId } : null;
  let writeIssued = false;
  const current = () => currentContext(options, actor);
  const cancelled = (): CurrentApprovalResult => ({
    kind: writeIssued ? "uncertain" : "cancelled",
  });
  if (
    !initial ||
    !actor ||
    !current() ||
    !approvalStillCurrentForActor(selected, initial.rows, action, actor.projectId, actor.actorId)
  )
    return { kind: "forbidden" };
  try {
    const prepared = await prepareDecision(selected, action, actor, options, current, cancelled);
    if (prepared.kind !== "prepared") return prepared;
    writeIssued = true;
    const decision = await options.port.resolve(prepared.fresh, action, options.signal);
    if (!current()) return cancelled();
    return await reconcileDecision(decision, selected, actor, options, current, cancelled);
  } catch {
    return failedDecision(writeIssued, options.signal);
  }
}
