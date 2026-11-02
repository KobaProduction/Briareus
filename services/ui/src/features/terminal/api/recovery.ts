import { recordValue } from "@/shared/lib/transport";
import { isUuid4 } from "@/shared/lib/uuid";
import type { TerminalRecovery, TerminalStart } from "../model/contracts";

function decodeRecovery(value: unknown, project: string | null): TerminalRecovery | null {
  const row = recordValue(value),
    args = recordValue(row?.arguments);
  if (
    !row ||
    !args ||
    row.project_uuid !== project ||
    !isUuid4(row.project_uuid) ||
    !isUuid4(row.operation_uuid) ||
    row.human !== true ||
    "agent_session_uuid" in row ||
    "expected_grant_revision" in row ||
    row.tool !== "job_start" ||
    args.workspace_id !== "default" ||
    args.interactive !== false ||
    typeof args.command !== "string"
  )
    return null;
  return {
    intent: {
      operation_uuid: row.operation_uuid,
      project_uuid: row.project_uuid,
      tool: "job_start",
      arguments: { workspace_id: "default", command: args.command, interactive: false },
    },
    jobId: typeof row.job_id === "string" && /^[a-f0-9]{32}$/.test(row.job_id) ? row.job_id : "",
  };
}
export function restoreTerminalRecovery(
  key: string,
  project: string | null,
): TerminalRecovery | null {
  try {
    const saved = sessionStorage.getItem(key);
    return saved && saved.length <= 32768 ? decodeRecovery(JSON.parse(saved), project) : null;
  } catch {
    return null;
  }
}
export function saveTerminalRecovery(key: string, intent: TerminalStart, jobId?: string): void {
  sessionStorage.setItem(
    key,
    JSON.stringify({ human: true, ...intent, ...(jobId ? { job_id: jobId } : {}) }),
  );
}
export function forgetTerminalRecovery(key: string): void {
  sessionStorage.removeItem(key);
}
