import type { ElevationPolicy } from "@/entities/agent-session";
import type { NormalSessionResult, SessionCommandPort } from "./contracts";
import { normalSessionReplayRemaining } from "./open-intent";
import type {
  PendingSessionOpen,
  SessionOpenRecovery,
  SessionOpenReservation,
} from "./open-recovery";
export interface NormalOpenContext {
  ownerKey: string;
  actorId: string;
  projectId: string;
  proofExpiresAt: string;
  canOpen: boolean;
}
type Verification = "authorized" | "unauthorized" | "forbidden" | "unavailable";
export type VerifiedNormalOpen = NormalSessionResult | { kind: "cancelled"; code: string };
interface OpenSessionOptions {
  port: SessionCommandPort;
  policy: ElevationPolicy;
  label: string;
  saved: PendingSessionOpen | null;
  journal: SessionOpenRecovery;
  signal: AbortSignal;
  context: () => NormalOpenContext | null;
  verify: (signal: AbortSignal) => Promise<Verification>;
}
function currentOpenContext(
  options: OpenSessionOptions,
  initial: NormalOpenContext | null,
): boolean {
  const value = options.context();
  return (
    !!initial &&
    !!value &&
    !options.signal.aborted &&
    value.ownerKey === initial.ownerKey &&
    value.actorId === initial.actorId &&
    value.projectId === initial.projectId &&
    value.canOpen &&
    Date.parse(value.proofExpiresAt) > Date.now()
  );
}
function savedIntentMatches(options: OpenSessionOptions, initial: NormalOpenContext): boolean {
  const saved = options.saved;
  return (
    !saved ||
    (options.journal.isCurrent(saved) &&
      saved.ownerKey === initial.ownerKey &&
      saved.command.project === initial.projectId)
  );
}
function settleOpenIntent(
  options: OpenSessionOptions,
  entry: PendingSessionOpen,
  result: NormalSessionResult,
): void {
  if (
    result.kind === "created" ||
    (!options.saved && ["unauthorized", "forbidden", "invalid"].includes(result.kind))
  ) {
    options.journal.complete(entry);
  }
}
function reserveOpenIntent(
  options: OpenSessionOptions,
  initial: NormalOpenContext,
): SessionOpenReservation {
  return options.saved
    ? { kind: "reserved", entry: options.saved }
    : options.journal.reserve(initial.ownerKey, initial.projectId, options.policy, options.label);
}
function failedOpen(dispatched: boolean, signal: AbortSignal): VerifiedNormalOpen {
  if (dispatched) return { kind: "uncertain", code: "SESSION_OPEN_FLOW_UNAVAILABLE" };
  return {
    kind: signal.aborted ? "cancelled" : "unavailable",
    code: "SESSION_OPEN_FLOW_UNAVAILABLE",
  };
}
async function dispatchOpenIntent(
  options: OpenSessionOptions,
  entry: PendingSessionOpen,
  current: () => boolean,
  invalidated: () => VerifiedNormalOpen,
): Promise<VerifiedNormalOpen> {
  const result = await options.port.executeOpen(entry.command, options.signal);
  if (!current() || !options.journal.isCurrent(entry)) return invalidated();
  settleOpenIntent(options, entry, result);
  return result;
}
/** Fresh owner check -> reserve one immutable intent -> one POST. The same
 * journal survives widget unmounts. A denial during retry cannot settle an
 * earlier ambiguous creation, and a different actor cannot consume it.
 */
export async function openVerifiedNormalSession(
  options: OpenSessionOptions,
): Promise<VerifiedNormalOpen> {
  const first = options.context(),
    initial = first ? { ...first } : null,
    saved = options.saved;
  let dispatched = false;
  const current = (): boolean => currentOpenContext(options, initial);
  const invalidated = (): VerifiedNormalOpen => ({
    kind: dispatched ? "uncertain" : "cancelled",
    code: "SESSION_OPEN_CONTEXT_CHANGED",
  });
  if (!current() || !initial) return invalidated();
  if (!savedIntentMatches(options, initial)) return invalidated();
  if (saved && normalSessionReplayRemaining(saved.command) <= 0)
    return { kind: "unavailable", code: "SESSION_RECOVERY_WINDOW_ELAPSED" };
  try {
    const proof = await options.verify(options.signal);
    if (!current()) return invalidated();
    if (proof !== "authorized") return { kind: proof, code: "SESSION_OWNER_NOT_VERIFIED" };
    const reserved = reserveOpenIntent(options, initial);
    if (reserved.kind !== "reserved") return reserved;
    const entry = reserved.entry;
    if (!current() || !options.journal.isCurrent(entry)) return invalidated();
    dispatched = true;
    return await dispatchOpenIntent(options, entry, current, invalidated);
  } catch {
    return failedOpen(dispatched, options.signal);
  }
}
