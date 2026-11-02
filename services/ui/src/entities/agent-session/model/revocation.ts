import { exactProjectionFields } from "@/shared/lib/owner-projection";
import { recordValue } from "@/shared/lib/transport";

export interface AgentSessionRevocation {
  session_uuid: string;
  project_uuid: string;
  status: "revoked";
  revision: number;
}

/** A fenced owner receipt still requires the feature's independent current-session readback. */
export function parseSessionRevocation(
  value: unknown,
  project: string,
  session: string,
  previousRevision: number,
): AgentSessionRevocation | null {
  const row = recordValue(value);
  if (
    !row ||
    !exactProjectionFields(row, ["session_uuid", "project_uuid", "status", "revision"]) ||
    row.session_uuid !== session ||
    row.project_uuid !== project ||
    row.status !== "revoked" ||
    typeof row.revision !== "number" ||
    !Number.isSafeInteger(row.revision) ||
    row.revision <= previousRevision
  )
    return null;
  return {
    session_uuid: session,
    project_uuid: project,
    status: "revoked",
    revision: row.revision,
  };
}
