import type { ApprovalAction, ApprovalRecord } from "./types";
/** These fields describe the user's original requested effect, not the
 * resolution. Reordering is allowed; resource substitution is not. */
export function sameRequestedEffect(a: ApprovalRecord, b: ApprovalRecord): boolean {
  const scopes = (row: ApprovalRecord) =>
    row.requested_resources
      .map((scope) =>
        JSON.stringify([
          scope.hand,
          scope.tool,
          scope.action,
          scope.resource.kind,
          scope.resource.id,
        ]),
      )
      .sort();
  return (
    a.project_uuid === b.project_uuid &&
    a.agent_session_uuid === b.agent_session_uuid &&
    a.requested_by_user_uuid === b.requested_by_user_uuid &&
    Date.parse(a.requested_expires_at) === Date.parse(b.requested_expires_at) &&
    JSON.stringify([...a.requested_operations].sort()) ===
      JSON.stringify([...b.requested_operations].sort()) &&
    JSON.stringify(scopes(a)) === JSON.stringify(scopes(b))
  );
}
/** UI-only stale-dialog guard. A fresh server proof is still required and
 * Backend owns the actual Cedar decision. Prevents a dialog opened for the
 * previous selected Project/actor or revision from issuing a write later.
 */
export function approvalStillCurrentForActor(
  selected: ApprovalRecord,
  currentRows: readonly ApprovalRecord[],
  action: ApprovalAction,
  projectUuid: string,
  actorUuid: string,
  now = Date.now(),
): boolean {
  const fresh = currentRows.find((row) => row.id === selected.id);
  return (
    !!fresh &&
    selected.project_uuid === projectUuid &&
    fresh.project_uuid === projectUuid &&
    fresh.version === selected.version &&
    sameRequestedEffect(fresh, selected) &&
    fresh.status === "pending" &&
    fresh.allowed_actions.includes(action) &&
    Date.parse(fresh.requested_expires_at) > now &&
    fresh.requested_by_user_uuid !== actorUuid
  );
}
