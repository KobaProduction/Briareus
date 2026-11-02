import type { ApprovalCommandPort, ApprovalResolution, ApprovalResult } from "../model/contracts";

export type { ApprovalResolution, ApprovalResult } from "../model/contracts";

import {
  type ApprovalAction,
  type ApprovalRecord,
  parseApproval,
  parseApprovalInventory,
  sameRequestedEffect,
} from "@/entities/approval";
import { CONTROL_PANEL_API_V1 } from "@/shared/config";
import {
  controlPanelHttpFailure as failure,
  readBoundedErrorCode,
  readBoundedJsonResponse,
  sameOriginJsonCommand,
  sameOriginJsonRequest,
} from "@/shared/lib/transport";
import { isUuid4 as uuid } from "@/shared/lib/uuid";

/** SOURCE contract: Backend services/api/src/control_panel_api/_oidc_approvals.py.
 * This Control Panel API is cookie-bound and defaults to 503 until the real
 * Authorization/Platform owner adapter is installed. Never mint grants in UI.
 */
export async function readProjectApprovals(
  projectUuid: string,
  signal: AbortSignal,
): Promise<ApprovalResult> {
  if (!uuid(projectUuid)) return { kind: "invalid", code: "INVALID_PROJECT_UUID" };
  if (signal.aborted) return { kind: "unavailable", code: "APPROVAL_READ_CANCELLED" };
  try {
    const response = await fetch(
      CONTROL_PANEL_API_V1 + "/approvals?project_uuid=" + encodeURIComponent(projectUuid),
      sameOriginJsonRequest(signal),
    );
    if (signal.aborted) return { kind: "unavailable", code: "APPROVAL_READ_CANCELLED" };
    if (response.status !== 200) {
      const code = await readBoundedErrorCode(response, signal, "UNKNOWN");
      if (signal.aborted) return { kind: "unavailable", code: "APPROVAL_READ_CANCELLED" };
      return failure(response.status, code);
    }
    const body = await readBoundedJsonResponse(response, signal, 6_291_456);
    if (signal.aborted) return { kind: "unavailable", code: "APPROVAL_READ_CANCELLED" };
    const items = parseApprovalInventory(body, projectUuid);
    if (!items) return { kind: "invalid", code: "APPROVAL_DTO_INVALID" };
    if (signal.aborted) return { kind: "unavailable", code: "APPROVAL_READ_CANCELLED" };
    return { kind: "ready", items };
  } catch {
    return {
      kind: "unavailable",
      code: signal.aborted ? "APPROVAL_READ_CANCELLED" : "APPROVAL_NETWORK_UNAVAILABLE",
    };
  }
}
/** The server owns the write and its idempotency. No UI optimistic approval. */
export async function resolveProjectApproval(
  item: ApprovalRecord,
  action: ApprovalAction,
  signal: AbortSignal,
): Promise<ApprovalResolution> {
  if (signal.aborted) return { kind: "unavailable", code: "APPROVAL_CANCELLED_BEFORE_DISPATCH" };
  if (
    !uuid(item.id) ||
    !uuid(item.project_uuid) ||
    item.status !== "pending" ||
    !item.allowed_actions.includes(action) ||
    !Number.isSafeInteger(item.version) ||
    Date.parse(item.requested_expires_at) <= Date.now()
  )
    return { kind: "invalid", code: "APPROVAL_ACTION_NOT_ALLOWED" };
  // Must run only in a browser secure context with real UUIDv4 crypto.
  if (typeof crypto === "undefined" || typeof crypto.randomUUID !== "function") {
    return { kind: "unavailable", code: "SECURE_CONTEXT_REQUIRED" };
  }
  const operation = crypto.randomUUID();
  try {
    const response = await fetch(
      CONTROL_PANEL_API_V1 + "/approvals/" + item.id + "/resolve",
      sameOriginJsonCommand(
        signal,
        operation,
        JSON.stringify({
          project_uuid: item.project_uuid,
          approve: action === "approve",
          expected_approval_version: item.version,
        }),
      ),
    );
    if (signal.aborted) return { kind: "uncertain", code: "APPROVAL_RESULT_UNCERTAIN" };
    if (response.status !== 200) {
      const code = await readBoundedErrorCode(response, signal, "UNKNOWN");
      if (signal.aborted) return { kind: "uncertain", code: "APPROVAL_RESULT_UNCERTAIN" };
      const fail = failure(response.status, code);
      return { kind: fail.kind, code: fail.code };
    }
    const row = parseApproval(
      await readBoundedJsonResponse(response, signal, 131_072),
      item.project_uuid,
    );
    if (signal.aborted) return { kind: "uncertain", code: "APPROVAL_RESULT_UNCERTAIN" };
    if (
      !row ||
      row.id !== item.id ||
      row.version !== item.version + 1 ||
      !sameRequestedEffect(row, item) ||
      row.status !== (action === "approve" ? "approved" : "rejected") ||
      row.allowed_actions.length !== 0
    )
      return { kind: "uncertain", code: "APPROVAL_RESULT_NOT_VERIFIED" };
    return { kind: "confirmed", item: row };
  } catch {
    return { kind: "uncertain", code: "APPROVAL_RESULT_UNCERTAIN" };
  }
}

export const approvalCommands: ApprovalCommandPort = {
  read: readProjectApprovals,
  resolve: resolveProjectApproval,
};
