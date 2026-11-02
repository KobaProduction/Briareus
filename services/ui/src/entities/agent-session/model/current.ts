import { parseHandEffectScopes } from "@/shared/lib/hand-effect-scope";
import { recordValue } from "@/shared/lib/transport";
import {
  exactProjectionFields,
  ownerDescription,
  ownerInstant,
  ownerOperations,
  positiveRevision,
} from "@/shared/lib/owner-projection";
import { isUuid4 } from "@/shared/lib/uuid";
import type { CurrentAgentSession, SessionStatus } from "./types";

const SESSION_FIELDS = [
  "session_uuid",
  "project_uuid",
  "created_by_user_uuid",
  "revision",
  "status",
  "is_elevated",
  "elevation_policy",
  "hard_expires_at",
  "operations",
  "resources",
  "allowed_actions",
] as const;
type SessionFacts = Omit<CurrentAgentSession, "operations" | "resources" | "allowed_actions">;
function sessionStatus(value: unknown): value is SessionStatus {
  return value === "active" || value === "expired" || value === "revoked";
}
function currentLifetime(status: SessionStatus, expires: string, now: number): boolean {
  if (status === "active") return Date.parse(expires) > now;
  return status !== "expired" || Date.parse(expires) <= now;
}
function sessionFacts(
  row: Record<string, unknown>,
  project: string,
  actor: string,
  canApprove: boolean,
  now: number,
): SessionFacts | null {
  if (
    !isUuid4(row.session_uuid) ||
    row.project_uuid !== project ||
    !isUuid4(row.created_by_user_uuid)
  )
    return null;
  if (!canApprove && row.created_by_user_uuid !== actor) return null;
  if (
    !positiveRevision(row.revision) ||
    !sessionStatus(row.status) ||
    typeof row.is_elevated !== "boolean"
  )
    return null;
  if (row.elevation_policy !== "fixed" && row.elevation_policy !== "requestable") return null;
  if (!ownerInstant(row.hard_expires_at) || !currentLifetime(row.status, row.hard_expires_at, now))
    return null;
  const description = ownerDescription(row);
  if (!description) return null;
  return {
    ...description,
    session_uuid: row.session_uuid,
    project_uuid: project,
    created_by_user_uuid: row.created_by_user_uuid,
    revision: row.revision,
    status: row.status,
    is_elevated: row.is_elevated,
    elevation_policy: row.elevation_policy,
    hard_expires_at: row.hard_expires_at,
  };
}
function revokeActions(
  value: unknown,
  facts: SessionFacts,
  canApprove: boolean,
  now: number,
): "revoke"[] | null {
  if (!Array.isArray(value) || value.length > 1) return null;
  if (value.length === 0) return [];
  if (
    value[0] !== "revoke" ||
    !canApprove ||
    facts.status !== "active" ||
    Date.parse(facts.hard_expires_at) <= now
  )
    return null;
  return ["revoke"];
}
/** A current owner projection, never an authority grant synthesized by the UI. */
export function parseCurrentSession(
  value: unknown,
  project: string,
  actor: string,
  canApprove: boolean,
  now = Date.now(),
): CurrentAgentSession | null {
  const row = recordValue(value);
  if (!row || !exactProjectionFields(row, SESSION_FIELDS, ["label", "created_at"])) return null;
  const facts = sessionFacts(row, project, actor, canApprove, now),
    operations = ownerOperations(row.operations);
  if (!facts || !operations || !Array.isArray(row.resources) || row.resources.length > 32)
    return null;
  const resources = parseHandEffectScopes(row.resources, operations, project),
    actions = revokeActions(row.allowed_actions, facts, canApprove, now);
  if (!resources || !actions) return null;
  return { ...facts, operations, resources, allowed_actions: actions };
}
export function parseSessionInventory(
  value: unknown,
  project: string,
  actor: string,
  canApprove: boolean,
): CurrentAgentSession[] | null {
  const data = recordValue(value);
  if (
    !data ||
    !exactProjectionFields(data, ["items"]) ||
    !Array.isArray(data.items) ||
    data.items.length > 50
  )
    return null;
  const seen = new Set<string>(),
    items: CurrentAgentSession[] = [];
  for (const row of data.items) {
    const item = parseCurrentSession(row, project, actor, canApprove);
    if (!item || seen.has(item.session_uuid)) return null;
    seen.add(item.session_uuid);
    items.push(item);
  }
  return items;
}
