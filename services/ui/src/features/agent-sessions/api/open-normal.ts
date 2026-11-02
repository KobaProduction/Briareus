import type { NormalSessionResult } from "../model/contracts";

export type { NormalSessionResult } from "../model/contracts";

import {
  knownPreparedOpen,
  normalSessionReplayRemaining,
  type PreparedNormalSessionOpen,
  prepareNormalSessionOpen,
} from "../model/open-intent";

export type { PreparedNormalSessionOpen, SessionOpenPreparation } from "../model/open-intent";
export { normalSessionReplayRemaining, prepareNormalSessionOpen } from "../model/open-intent";

import { type ElevationPolicy, parseNormalSession } from "@/entities/agent-session";
import { CONTROL_PANEL_API_V1 } from "@/shared/config";
import { readBoundedErrorCode, readBoundedJsonResponse } from "@/shared/lib/transport";

/** Source: Backend services/api/src/control_panel_api/_oidc_approvals.py
 * POST /api/v1/agent-sessions (local source only, owner default 503).
 * A verified 201 establishes only this returned normal session. Current
 * inventory is read independently; this response is not elevated permission.
 */
/** An immutable request intent, kept in memory until its outcome is known.
 * Replays reuse these exact serialized bytes and the original operation UUID.
 */
function openRefusal(status: number, code: string): NormalSessionResult {
  const kinds: Partial<Record<number, "unauthorized" | "forbidden" | "conflict" | "invalid">> = {
    401: "unauthorized",
    403: "forbidden",
    409: "conflict",
    422: "invalid",
  };
  return { kind: kinds[status] ?? "uncertain", code };
}
async function openResult(
  response: Response,
  command: PreparedNormalSessionOpen,
  signal: AbortSignal,
): Promise<NormalSessionResult> {
  if (response.status === 201) {
    const record = parseNormalSession(
      await readBoundedJsonResponse(response, signal, 16_384),
      command.project,
      command.policy,
    );
    if (signal.aborted) return { kind: "uncertain", code: "SESSION_OPEN_OUTCOME_UNCERTAIN" };
    return record
      ? { kind: "created", session: record }
      : { kind: "uncertain", code: "SESSION_RESULT_NOT_VERIFIED" };
  }
  const code = await readBoundedErrorCode(response, signal, "UNKNOWN");
  if (signal.aborted) return { kind: "uncertain", code: "SESSION_OPEN_OUTCOME_UNCERTAIN" };
  return openRefusal(response.status, code);
}
export async function executeNormalSessionOpen(
  command: PreparedNormalSessionOpen,
  signal: AbortSignal,
): Promise<NormalSessionResult> {
  if (!knownPreparedOpen(command)) return { kind: "invalid", code: "SESSION_COMMAND_NOT_PREPARED" };
  if (normalSessionReplayRemaining(command) <= 0)
    return { kind: "unavailable", code: "SESSION_RECOVERY_WINDOW_ELAPSED" };
  if (signal.aborted) return { kind: "unavailable", code: "SESSION_COMMAND_CANCELLED" };
  const { operation, body } = command;
  try {
    const response = await fetch(`${CONTROL_PANEL_API_V1}/agent-sessions`, {
      method: "POST",
      credentials: "same-origin",
      mode: "same-origin",
      redirect: "error",
      referrerPolicy: "no-referrer",
      cache: "no-store",
      signal,
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "Operation-UUID": operation,
        "Idempotency-Key": operation,
      },
      body,
    });
    if (signal.aborted) return { kind: "uncertain", code: "SESSION_OPEN_OUTCOME_UNCERTAIN" };
    return await openResult(response, command, signal);
  } catch {
    return { kind: "uncertain", code: "SESSION_OPEN_OUTCOME_UNCERTAIN" };
  }
}
/** One-shot compatibility API. Interactive UI retains a prepared command so
 * an uncertain result can be reconciled without a second creation intent. */
export async function openNormalSession(
  project: string,
  policy: ElevationPolicy,
  label: string,
  signal: AbortSignal,
): Promise<NormalSessionResult> {
  const prepared = prepareNormalSessionOpen(project, policy, label);
  return prepared.kind === "prepared"
    ? executeNormalSessionOpen(prepared.command, signal)
    : prepared;
}
