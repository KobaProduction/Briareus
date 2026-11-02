import type { CurrentAgentSession } from "@/entities/agent-session";
import type { CurrentSessionRead, SessionCommandPort, SessionRevokeResult } from "./contracts";

export interface SessionCommandContext {
  projectId: string;
  actorId: string;
  proofExpiresAt: string;
  canApprove: boolean;
}
type Verification = "authorized" | "unauthorized" | "forbidden" | "unavailable";
export type ReconciledRevoke =
  | { kind: "confirmed" | "conflict" | "observed"; item: CurrentAgentSession }
  | {
      kind: "cancelled" | "unauthorized" | "forbidden" | "invalid" | "unavailable" | "uncertain";
      code: string;
    };

function canRevoke(selected: CurrentAgentSession, project: string | undefined): boolean {
  return (
    selected.project_uuid === project &&
    selected.status === "active" &&
    selected.allowed_actions.includes("revoke") &&
    Date.parse(selected.hard_expires_at) > Date.now()
  );
}
function unchangedSession(fresh: CurrentAgentSession, selected: CurrentAgentSession): boolean {
  return (
    fresh.revision === selected.revision &&
    fresh.created_by_user_uuid === selected.created_by_user_uuid &&
    fresh.status === "active" &&
    fresh.allowed_actions.includes("revoke")
  );
}
function failedRevoke(dispatched: boolean, signal: AbortSignal): ReconciledRevoke {
  if (dispatched) return { kind: "uncertain", code: "REVOKE_FLOW_UNAVAILABLE" };
  return { kind: signal.aborted ? "cancelled" : "unavailable", code: "REVOKE_FLOW_UNAVAILABLE" };
}
function unavailableBeforeRevoke(
  before: Exclude<CurrentSessionRead, { kind: "ready" }>,
): ReconciledRevoke {
  return {
    kind: before.kind === "conflict" || before.kind === "not_found" ? "unavailable" : before.kind,
    code: before.code,
  };
}
function terminalReceipt(receipt: SessionRevokeResult): ReconciledRevoke | null {
  if (receipt.kind === "confirmed" || receipt.kind === "conflict" || receipt.kind === "uncertain")
    return null;
  if (receipt.kind !== "unavailable") return { kind: receipt.kind, code: receipt.code };
  return ["SECURE_CONTEXT_REQUIRED", "REVOKE_CANCELLED_BEFORE_DISPATCH"].includes(receipt.code)
    ? { kind: "unavailable", code: receipt.code }
    : null;
}
function reconcileRevoke(
  receipt: SessionRevokeResult,
  after: CurrentAgentSession,
  selected: CurrentAgentSession,
): ReconciledRevoke {
  if (
    after.created_by_user_uuid !== selected.created_by_user_uuid ||
    after.revision < selected.revision
  ) {
    return { kind: "uncertain", code: "REVOKE_RESULT_CONTRADICTED" };
  }
  if (receipt.kind === "conflict") return { kind: "conflict", item: after };
  // Observing a changed row cannot replace a lost POST receipt.
  if (receipt.kind !== "confirmed") return { kind: "observed", item: after };
  if (
    after.status !== "revoked" ||
    after.revision < receipt.revision ||
    after.allowed_actions.length !== 0
  ) {
    return { kind: "uncertain", code: "REVOKE_RESULT_CONTRADICTED" };
  }
  return { kind: "confirmed", item: after };
}
async function reconcileCurrentRevoke(
  receipt: SessionRevokeResult,
  selected: CurrentAgentSession,
  port: SessionCommandPort,
  initial: SessionCommandContext,
  signal: AbortSignal,
  current: () => boolean,
  invalidated: () => ReconciledRevoke,
): Promise<ReconciledRevoke> {
  const terminal = terminalReceipt(receipt);
  if (terminal) return terminal;
  const after = await port.read(
    initial.projectId,
    selected.session_uuid,
    initial.actorId,
    true,
    signal,
  );
  if (!current()) return invalidated();
  if (after.kind !== "ready") return { kind: "uncertain", code: "REVOKE_NOT_RECONCILED" };
  return reconcileRevoke(receipt, after.item, selected);
}

/** Fresh Project membership -> exact current row -> one revision-fenced POST
 * -> exact current row. List truncation cannot masquerade as a revoke result.
 * UI context is a cancellation guard, never a server authorization grant.
 */
export async function revokeVerifiedSession(
  selected: CurrentAgentSession,
  options: {
    port: SessionCommandPort;
    signal: AbortSignal;
    context: () => SessionCommandContext | null;
    verify: (signal: AbortSignal) => Promise<Verification>;
  },
): Promise<ReconciledRevoke> {
  const initial = options.context();
  const project = initial?.projectId,
    actor = initial?.actorId;
  const id = selected.session_uuid;
  let dispatched = false;
  const current = (): boolean => {
    const context = options.context();
    return (
      !options.signal.aborted &&
      !!initial &&
      !!context &&
      context.projectId === project &&
      context.actorId === actor &&
      context.canApprove &&
      Date.parse(context.proofExpiresAt) > Date.now()
    );
  };
  const invalidated = (): ReconciledRevoke => ({
    kind: dispatched ? "uncertain" : "cancelled",
    code: "REVOKE_CONTEXT_CHANGED",
  });
  if (!initial || !canRevoke(selected, project)) {
    return { kind: "forbidden", code: "REVOKE_NOT_ALLOWED" };
  }
  if (!current()) return invalidated();
  try {
    const verdict = await options.verify(options.signal);
    if (!current()) return invalidated();
    if (verdict !== "authorized") return { kind: verdict, code: "REVOKE_OWNER_NOT_VERIFIED" };
    const before = await options.port.read(
      initial.projectId,
      id,
      initial.actorId,
      true,
      options.signal,
    );
    if (!current()) return invalidated();
    if (before.kind !== "ready") return unavailableBeforeRevoke(before);
    const fresh = before.item;
    if (!unchangedSession(fresh, selected)) {
      return { kind: "conflict", item: fresh };
    }
    dispatched = true;
    const receipt = await options.port.revoke(fresh, options.signal);
    if (!current()) return invalidated();
    return await reconcileCurrentRevoke(
      receipt,
      selected,
      options.port,
      initial,
      options.signal,
      current,
      invalidated,
    );
  } catch {
    return failedRevoke(dispatched, options.signal);
  }
}
