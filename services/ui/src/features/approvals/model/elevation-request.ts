import { type ElevationTarget, elevationTargetAllowed } from "@/entities/agent-session";
import type { ApprovalRecord } from "@/entities/approval";
import {
  type HandEffectScope,
  hasCompleteHandScopeCoverage,
  parseHandEffectScopes,
} from "@/shared/lib/hand-effect-scope";

export type ElevationRequestResult =
  | { kind: "pending"; item: ApprovalRecord }
  | {
      kind: "unauthorized" | "forbidden" | "conflict" | "invalid" | "unavailable" | "uncertain";
      code: string;
    };
export interface ElevationIntent {
  project: string;
  session: string;
  revision: number;
  actor: string;
  seconds: number;
  operations: string[];
  resources: HandEffectScope[];
  resourceKeys: string[];
}
type PreparedElevation =
  | { kind: "prepared"; intent: ElevationIntent }
  | { kind: "invalid"; code: string };
function scopeKey(scope: HandEffectScope): string {
  return JSON.stringify([
    scope.hand,
    scope.tool,
    scope.action,
    scope.resource.kind,
    scope.resource.id,
  ]);
}
export function prepareElevationRequest(
  target: ElevationTarget,
  requested: readonly HandEffectScope[],
  seconds: number,
  actor: string,
): PreparedElevation {
  if (
    !elevationTargetAllowed(target, actor, seconds) ||
    !Array.isArray(requested) ||
    requested.length < 1 ||
    requested.length > 32
  )
    return { kind: "invalid", code: "ELEVATION_REQUEST_INVALID" };
  const operations = [...new Set(requested.map((scope) => scope?.action))];
  const resources = parseHandEffectScopes(requested, operations, target.project_uuid);
  if (!resources || !hasCompleteHandScopeCoverage(operations, resources))
    return { kind: "invalid", code: "ELEVATION_SCOPE_INVALID" };
  return {
    kind: "prepared",
    intent: {
      project: target.project_uuid,
      session: target.session_uuid,
      revision: target.revision,
      actor,
      seconds,
      operations,
      resources,
      resourceKeys: resources.map(scopeKey).sort(),
    },
  };
}
export function pendingElevationMatches(
  row: ApprovalRecord,
  operation: string,
  intent: ElevationIntent,
): boolean {
  if (
    row.id !== operation ||
    row.agent_session_uuid !== intent.session ||
    row.requested_by_user_uuid !== intent.actor
  )
    return false;
  if (
    row.status !== "pending" ||
    row.version !== 1 ||
    row.allowed_actions.length !== 0 ||
    row.resolved_by_user_uuid !== null ||
    row.issued_session_uuid !== null
  )
    return false;
  const expires = Date.parse(row.requested_expires_at);
  if (!(expires > Date.now()) || expires > Date.now() + intent.seconds * 1000 + 1000) return false;
  if (
    row.requested_operations.length !== intent.operations.length ||
    row.requested_operations.some((action) => !intent.operations.includes(action))
  )
    return false;
  return (
    JSON.stringify(row.requested_resources.map(scopeKey).sort()) ===
    JSON.stringify(intent.resourceKeys)
  );
}
