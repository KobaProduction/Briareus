import { recordValue as object } from "@/shared/lib/transport";
import { isUuid4 } from "@/shared/lib/uuid";
import type { ElevationPolicy, NormalSession } from "./types";
export const NORMAL_SESSION_MAX_AGE_MS = 24 * 60 * 60 * 1000;
export function parseNormalSession(
  value: unknown,
  project: string,
  policy: ElevationPolicy,
  now = Date.now(),
): NormalSession | null {
  const r = object(value);
  if (
    !r ||
    Object.keys(r).length !== 9 ||
    ![
      "session_uuid",
      "project_uuid",
      "revision",
      "status",
      "is_elevated",
      "elevation_policy",
      "hard_expires_at",
      "operations",
      "resources",
    ].every((key) => Object.hasOwn(r, key)) ||
    !isUuid4(r.session_uuid) ||
    r.project_uuid !== project ||
    r.revision !== 1 ||
    r.status !== "active" ||
    r.is_elevated !== false ||
    r.elevation_policy !== policy ||
    typeof r.hard_expires_at !== "string" ||
    !/(?:Z|[+-][0-2][0-9]:[0-5][0-9])$/.test(r.hard_expires_at) ||
    !Number.isFinite(Date.parse(r.hard_expires_at)) ||
    Date.parse(r.hard_expires_at) <= now ||
    Date.parse(r.hard_expires_at) > now + NORMAL_SESSION_MAX_AGE_MS + 1000 ||
    !Array.isArray(r.operations) ||
    r.operations.length !== 2 ||
    r.operations[0] !== "files.read" ||
    r.operations[1] !== "project.metadata.read" ||
    !Array.isArray(r.resources) ||
    r.resources.length !== 0
  )
    return null;
  return {
    session_uuid: r.session_uuid,
    project_uuid: project,
    revision: 1,
    status: "active",
    is_elevated: false,
    elevation_policy: policy,
    hard_expires_at: r.hard_expires_at,
    operations: ["files.read", "project.metadata.read"],
    resources: [],
  };
}
