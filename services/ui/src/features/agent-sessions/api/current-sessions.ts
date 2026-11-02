import type { CurrentSessionRead, SessionInventory, SessionRevokeResult } from "../model/contracts";

export type { CurrentSessionRead, SessionInventory, SessionRevokeResult } from "../model/contracts";

/** Source-only peer Backend contract:
 * services/api/src/control_panel_api/_oidc_approvals.py (LOCAL, not released).
 * The owner independently authorizes Project scope and writes. This client
 * never turns a Rauthy identity or displayed allowed_actions into a Permit.
 */
import {
  type CurrentAgentSession,
  parseCurrentSession,
  parseSessionRevocation,
  parseSessionInventory,
} from "@/entities/agent-session";
import { CONTROL_PANEL_API_V1 } from "@/shared/config";
import {
  controlPanelHttpFailure as fail,
  readBoundedErrorCode,
  readBoundedJsonResponse,
  sameOriginJsonCommand,
  sameOriginJsonRequest,
} from "@/shared/lib/transport";

export { isUuid4 as isCurrentSessionId } from "@/shared/lib/uuid";

import { isUuid4 as uuid } from "@/shared/lib/uuid";

async function currentReadFailure(
  response: Response,
  signal: AbortSignal,
): Promise<Exclude<CurrentSessionRead, { kind: "ready" }>> {
  const code = await readBoundedErrorCode(response, signal, "UNKNOWN");
  if (signal.aborted) return { kind: "unavailable", code: "AGENT_SESSION_READ_CANCELLED" };
  if (response.status === 404 && code === "AGENT_SESSION_NOT_FOUND")
    return { kind: "not_found", code };
  return fail(response.status, code);
}
/** Backend uses the same owner and projection validation as inventory.
 * A missing record/route or invalid response is not proof of revocation.
 */
export async function readCurrentSession(
  projectUuid: string,
  sessionUuid: string,
  actorUuid: string,
  canApprove: boolean,
  signal: AbortSignal,
): Promise<CurrentSessionRead> {
  if (!uuid(projectUuid) || !uuid(sessionUuid) || !uuid(actorUuid))
    return { kind: "invalid", code: "INVALID_SCOPE" };
  if (signal.aborted) return { kind: "unavailable", code: "AGENT_SESSION_READ_CANCELLED" };
  try {
    const response = await fetch(
      CONTROL_PANEL_API_V1 + "/agent-sessions/" + sessionUuid + "?project_uuid=" + projectUuid,
      { method: "GET", ...sameOriginJsonRequest(signal) },
    );
    if (signal.aborted) return { kind: "unavailable", code: "AGENT_SESSION_READ_CANCELLED" };
    if (response.status !== 200) return await currentReadFailure(response, signal);
    const item = parseCurrentSession(
      await readBoundedJsonResponse(response, signal, 131_072),
      projectUuid,
      actorUuid,
      canApprove,
    );
    if (signal.aborted) return { kind: "unavailable", code: "AGENT_SESSION_READ_CANCELLED" };
    if (!item || item.session_uuid !== sessionUuid)
      return { kind: "invalid", code: "AGENT_SESSION_DTO_INVALID" };
    return { kind: "ready", item };
  } catch {
    return {
      kind: "unavailable",
      code: signal.aborted ? "AGENT_SESSION_READ_CANCELLED" : "AGENT_SESSION_READ_UNAVAILABLE",
    };
  }
}
export async function listCurrentSessions(
  projectUuid: string,
  actorUuid: string,
  canApprove: boolean,
  signal: AbortSignal,
): Promise<SessionInventory> {
  if (!uuid(projectUuid) || !uuid(actorUuid)) return { kind: "invalid", code: "INVALID_SCOPE" };
  if (signal.aborted) return { kind: "unavailable", code: "AGENT_SESSION_LIST_CANCELLED" };
  try {
    const response = await fetch(
      `${CONTROL_PANEL_API_V1}/agent-sessions?project_uuid=${projectUuid}`,
      { method: "GET", ...sameOriginJsonRequest(signal) },
    );
    if (signal.aborted) return { kind: "unavailable", code: "AGENT_SESSION_LIST_CANCELLED" };
    if (response.status !== 200) {
      const code = await readBoundedErrorCode(response, signal, "UNKNOWN");
      if (signal.aborted) return { kind: "unavailable", code: "AGENT_SESSION_LIST_CANCELLED" };
      return fail(response.status, code);
    }
    const data = await readBoundedJsonResponse(response, signal, 6_291_456);
    if (signal.aborted) return { kind: "unavailable", code: "AGENT_SESSION_LIST_CANCELLED" };
    const items = parseSessionInventory(data, projectUuid, actorUuid, canApprove);
    if (!items) return { kind: "invalid", code: "AGENT_SESSION_DTO_INVALID" };
    if (signal.aborted) return { kind: "unavailable", code: "AGENT_SESSION_LIST_CANCELLED" };
    return { kind: "ready", items };
  } catch {
    return {
      kind: "unavailable",
      code: signal.aborted ? "AGENT_SESSION_LIST_CANCELLED" : "AGENT_SESSION_LIST_UNAVAILABLE",
    };
  }
}
/** A version-fenced server-side revocation; caller must revalidate the
 * independent current approver privilege immediately before invoking this.
 * HTTP 200 is provisional until caller reads the exact current session.
 */
export async function revokeCurrentSession(
  session: CurrentAgentSession,
  signal: AbortSignal,
): Promise<SessionRevokeResult> {
  if (signal.aborted) return { kind: "unavailable", code: "REVOKE_CANCELLED_BEFORE_DISPATCH" };
  const project = session.project_uuid,
    id = session.session_uuid,
    revision = session.revision;
  if (
    !uuid(project) ||
    !uuid(id) ||
    session.status !== "active" ||
    !session.allowed_actions.includes("revoke") ||
    !Number.isSafeInteger(session.revision) ||
    session.revision < 1 ||
    Date.parse(session.hard_expires_at) <= Date.now()
  )
    return { kind: "invalid", code: "REVOKE_NOT_ALLOWED" };
  if (typeof crypto === "undefined" || typeof crypto.randomUUID !== "function")
    return { kind: "unavailable", code: "SECURE_CONTEXT_REQUIRED" };
  const operation = crypto.randomUUID();
  try {
    const response = await fetch(
      `${CONTROL_PANEL_API_V1}/agent-sessions/${id}/revoke`,
      sameOriginJsonCommand(
        signal,
        operation,
        JSON.stringify({
          project_uuid: project,
          expected_grant_revision: revision,
        }),
      ),
    );
    if (signal.aborted) return { kind: "uncertain", code: "REVOKE_RESULT_UNCERTAIN" };
    if (response.status !== 200) {
      const code = await readBoundedErrorCode(response, signal, "UNKNOWN");
      if (signal.aborted) return { kind: "uncertain", code: "REVOKE_RESULT_UNCERTAIN" };
      const result = fail(response.status, code);
      return { kind: result.kind, code: result.code };
    }
    const payload = await readBoundedJsonResponse(response, signal, 16_384);
    if (signal.aborted) return { kind: "uncertain", code: "REVOKE_RESULT_UNCERTAIN" };
    const result = parseSessionRevocation(payload, project, id, revision);
    if (!result) return { kind: "uncertain", code: "REVOKE_RESULT_UNVERIFIED" };
    return {
      kind: "confirmed",
      session_uuid: id,
      project_uuid: project,
      revision: result.revision,
    };
  } catch {
    return { kind: "uncertain", code: "REVOKE_RESULT_UNCERTAIN" };
  }
}
