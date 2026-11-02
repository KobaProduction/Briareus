import { ownerInstant, positiveRevision } from "@/shared/lib/owner-projection";
import { isUuid4 } from "@/shared/lib/uuid";
import type { CurrentAgentSession } from "./types";

export type ElevationTarget = Pick<
  CurrentAgentSession,
  "project_uuid" | "session_uuid" | "revision" | "status" | "elevation_policy" | "hard_expires_at"
>;
export function elevationTargetAllowed(
  target: ElevationTarget,
  actor: string,
  seconds: number,
): boolean {
  if (!isUuid4(target.project_uuid) || !isUuid4(target.session_uuid) || !isUuid4(actor))
    return false;
  if (
    target.status !== "active" ||
    target.elevation_policy !== "requestable" ||
    !positiveRevision(target.revision)
  )
    return false;
  if (!Number.isInteger(seconds) || seconds < 1 || seconds > 300) return false;
  return ownerInstant(target.hard_expires_at) && Date.parse(target.hard_expires_at) > Date.now();
}
