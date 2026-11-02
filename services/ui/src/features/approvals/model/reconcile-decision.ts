import { type ApprovalRecord, sameRequestedEffect } from "@/entities/approval";
import type { ApprovalResolution, CurrentApprovalResult } from "./contracts";

export function terminalApprovalDecision(
  decision: ApprovalResolution,
  actor: string,
): CurrentApprovalResult | null {
  if (
    decision.kind !== "confirmed" &&
    decision.kind !== "conflict" &&
    decision.kind !== "uncertain" &&
    decision.kind !== "unavailable"
  )
    return { kind: decision.kind };
  if (
    decision.kind === "unavailable" &&
    ["SECURE_CONTEXT_REQUIRED", "APPROVAL_CANCELLED_BEFORE_DISPATCH"].includes(decision.code)
  )
    return { kind: "unavailable" };
  if (decision.kind === "confirmed" && decision.item.resolved_by_user_uuid !== actor)
    return { kind: "uncertain" };
  return null;
}
/** A post-loss observation never becomes attribution to an unconfirmed command. */
export function reconcileApprovalDecision(
  decision: ApprovalResolution,
  selected: ApprovalRecord,
  items: ApprovalRecord[],
  actor: string,
): CurrentApprovalResult {
  const actual = items.find((row) => row.id === selected.id);
  if (!actual || !sameRequestedEffect(actual, selected)) return { kind: "uncertain" };
  if (decision.kind === "conflict") return { kind: "conflict", items };
  if (decision.kind !== "confirmed") {
    const expected = actual.status === "pending" ? selected.version : selected.version + 1;
    return actual.version === expected ? { kind: "observed", items } : { kind: "uncertain" };
  }
  if (
    actual.status !== decision.item.status ||
    actual.version !== decision.item.version ||
    actual.issued_session_uuid !== decision.item.issued_session_uuid ||
    actual.resolved_by_user_uuid !== actor
  )
    return { kind: "uncertain" };
  return { kind: "confirmed", items };
}
