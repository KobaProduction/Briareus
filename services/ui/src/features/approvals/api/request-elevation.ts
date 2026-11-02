import type { ElevationTarget } from "@/entities/agent-session";
import { parseApproval } from "@/entities/approval";
import { CONTROL_PANEL_API_V1 } from "@/shared/config";
import { readBoundedJsonResponse } from "@/shared/lib/transport";
import type { HandEffectScope } from "@/shared/lib/hand-effect-scope";
import {
  type ElevationIntent,
  type ElevationRequestResult,
  pendingElevationMatches,
  prepareElevationRequest,
} from "../model/elevation-request";

export type { ElevationTarget } from "@/entities/agent-session";
export type { ElevationRequestResult } from "../model/elevation-request";

function httpRefusal(status: number): ElevationRequestResult {
  const kinds: Partial<Record<number, "unauthorized" | "forbidden" | "conflict" | "invalid">> = {
    401: "unauthorized",
    403: "forbidden",
    409: "conflict",
    422: "invalid",
  };
  return { kind: kinds[status] ?? "uncertain", code: `ELEVATION_HTTP_${status}` };
}
async function pendingReply(
  response: Response,
  operation: string,
  intent: ElevationIntent,
  signal: AbortSignal,
): Promise<ElevationRequestResult> {
  if (response.status !== 202) return httpRefusal(response.status);
  const row = parseApproval(
    await readBoundedJsonResponse(response, signal, 131_072),
    intent.project,
  );
  if (signal.aborted) return { kind: "uncertain", code: "ELEVATION_OUTCOME_UNCERTAIN" };
  if (!row || !pendingElevationMatches(row, operation, intent))
    return { kind: "uncertain", code: "ELEVATION_PENDING_NOT_VERIFIED" };
  return { kind: "pending", item: row };
}
/** A pending owner request is never an elevated session or a Cedar Permit. */
export async function requestSessionElevation(
  target: ElevationTarget,
  requestedResources: readonly HandEffectScope[],
  seconds: number,
  actorUuid: string,
  signal: AbortSignal,
): Promise<ElevationRequestResult> {
  if (signal.aborted) return { kind: "unavailable", code: "APPROVAL_REQUEST_CANCELLED" };
  const prepared = prepareElevationRequest(target, requestedResources, seconds, actorUuid);
  if (prepared.kind !== "prepared") return prepared;
  if (typeof crypto === "undefined" || typeof crypto.randomUUID !== "function")
    return { kind: "unavailable", code: "SECURE_CONTEXT_REQUIRED" };
  const operation = crypto.randomUUID(),
    intent = prepared.intent;
  try {
    const response = await fetch(`${CONTROL_PANEL_API_V1}/approvals`, {
      method: "POST",
      signal,
      credentials: "same-origin",
      mode: "same-origin",
      redirect: "error",
      cache: "no-store",
      referrerPolicy: "no-referrer",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "Operation-UUID": operation,
        "Idempotency-Key": operation,
      },
      body: JSON.stringify({
        project_uuid: intent.project,
        agent_session_uuid: intent.session,
        operations: intent.operations,
        resources: intent.resources,
        seconds: intent.seconds,
        expected_grant_revision: intent.revision,
      }),
    });
    if (signal.aborted) return { kind: "uncertain", code: "ELEVATION_OUTCOME_UNCERTAIN" };
    return await pendingReply(response, operation, intent, signal);
  } catch {
    return { kind: "uncertain", code: "ELEVATION_OUTCOME_UNCERTAIN" };
  }
}
