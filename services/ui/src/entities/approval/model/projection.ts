import {
  hasCompleteHandScopeCoverage,
  parseHandEffectScopes,
} from "@/shared/lib/hand-effect-scope";
import { recordValue } from "@/shared/lib/transport";
import {
  exactProjectionFields,
  ownerDescription,
  ownerInstant,
  ownerOperations,
  positiveRevision,
} from "@/shared/lib/owner-projection";
import { isUuid4 } from "@/shared/lib/uuid";
import type { ApprovalAction, ApprovalRecord, ApprovalStatus } from "./types";

const APPROVAL_FIELDS = [
  "id",
  "project_uuid",
  "agent_session_uuid",
  "requested_by_user_uuid",
  "status",
  "version",
  "requested_operations",
  "requested_resources",
  "requested_expires_at",
  "resolved_by_user_uuid",
  "issued_session_uuid",
  "allowed_actions",
] as const;
type ApprovalFacts = Omit<
  ApprovalRecord,
  "requested_operations" | "requested_resources" | "allowed_actions"
>;
function approvalStatus(value: unknown): value is ApprovalStatus {
  return value === "pending" || value === "approved" || value === "rejected";
}
function nullableUuid(value: unknown): value is string | null {
  return value === null || isUuid4(value);
}
function resolutionConsistent(facts: ApprovalFacts): boolean {
  if (facts.status === "pending")
    return facts.resolved_by_user_uuid === null && facts.issued_session_uuid === null;
  return (
    facts.resolved_by_user_uuid !== null &&
    facts.resolved_by_user_uuid !== facts.requested_by_user_uuid &&
    (facts.status === "approved") === (facts.issued_session_uuid !== null) &&
    facts.issued_session_uuid !== facts.agent_session_uuid
  );
}
function approvalFacts(row: Record<string, unknown>, project: string): ApprovalFacts | null {
  if (
    !isUuid4(row.id) ||
    row.project_uuid !== project ||
    !isUuid4(row.agent_session_uuid) ||
    !isUuid4(row.requested_by_user_uuid)
  )
    return null;
  if (
    !approvalStatus(row.status) ||
    !positiveRevision(row.version) ||
    !ownerInstant(row.requested_expires_at)
  )
    return null;
  if (!nullableUuid(row.resolved_by_user_uuid) || !nullableUuid(row.issued_session_uuid))
    return null;
  const description = ownerDescription(row);
  if (!description) return null;
  const facts: ApprovalFacts = {
    ...description,
    id: row.id,
    project_uuid: project,
    agent_session_uuid: row.agent_session_uuid,
    requested_by_user_uuid: row.requested_by_user_uuid,
    status: row.status,
    version: row.version,
    requested_expires_at: row.requested_expires_at,
    resolved_by_user_uuid: row.resolved_by_user_uuid,
    issued_session_uuid: row.issued_session_uuid,
  };
  return resolutionConsistent(facts) ? facts : null;
}
function approvalActions(value: unknown, facts: ApprovalFacts): ApprovalAction[] | null {
  if (!Array.isArray(value) || value.length > 2 || new Set(value).size !== value.length)
    return null;
  if (
    (facts.status !== "pending" || Date.parse(facts.requested_expires_at) <= Date.now()) &&
    value.length !== 0
  )
    return null;
  const actions: ApprovalAction[] = [];
  for (const action of value) {
    if (action !== "approve" && action !== "deny") return null;
    actions.push(action);
  }
  return actions;
}
/** Exact owner evidence; pending approval cannot grant an action-only elevation. */
export function parseApproval(value: unknown, project: string): ApprovalRecord | null {
  const row = recordValue(value);
  if (!row || !exactProjectionFields(row, APPROVAL_FIELDS, ["label", "created_at"])) return null;
  const facts = approvalFacts(row, project),
    operations = ownerOperations(row.requested_operations);
  if (
    !facts ||
    !operations ||
    !Array.isArray(row.requested_resources) ||
    row.requested_resources.length > 32
  )
    return null;
  const resources = parseHandEffectScopes(row.requested_resources, operations, project),
    actions = approvalActions(row.allowed_actions, facts);
  if (!resources || !actions) return null;
  if (facts.status === "pending" && !hasCompleteHandScopeCoverage(operations, resources))
    return null;
  return {
    ...facts,
    requested_operations: operations,
    requested_resources: resources,
    allowed_actions: actions,
  };
}
export function parseApprovalInventory(value: unknown, project: string): ApprovalRecord[] | null {
  const data = recordValue(value);
  if (
    !data ||
    !exactProjectionFields(data, ["items"]) ||
    !Array.isArray(data.items) ||
    data.items.length > 50
  )
    return null;
  const ids = new Set<string>(),
    items: ApprovalRecord[] = [];
  for (const value of data.items) {
    const item = parseApproval(value, project);
    if (!item || ids.has(item.id)) return null;
    ids.add(item.id);
    items.push(item);
  }
  return items;
}
