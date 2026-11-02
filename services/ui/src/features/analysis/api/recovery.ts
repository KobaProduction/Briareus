import { recordValue } from "@/shared/lib/transport";
import { isUuid4 } from "@/shared/lib/uuid";
import type { AnalysisRecovery } from "../model/recovery";

function validOperation(value: string): boolean {
  const parts = value.split(":");
  return parts.length === 2 && isUuid4(parts[1]) && (parts[0] === "request" || isUuid4(parts[0]));
}
export function parseAnalysisRecovery(
  value: unknown,
  project: string | null,
): AnalysisRecovery | null {
  const row = recordValue(value);
  if (
    !row ||
    Object.keys(row).length !== 4 ||
    row.human !== true ||
    row.project_uuid !== project ||
    !isUuid4(row.project_uuid) ||
    (row.engine !== "radare2" && row.engine !== "ghidra") ||
    typeof row.operation_id !== "string" ||
    !validOperation(row.operation_id)
  )
    return null;
  return { engine: row.engine, operationId: row.operation_id };
}
export function restoreAnalysisRecovery(
  key: string,
  project: string | null,
): AnalysisRecovery | null {
  try {
    const saved = sessionStorage.getItem(key);
    return saved && saved.length <= 1024 ? parseAnalysisRecovery(JSON.parse(saved), project) : null;
  } catch {
    return null;
  }
}
export function saveAnalysisRecovery(
  key: string,
  project: string,
  recovery: AnalysisRecovery,
): void {
  sessionStorage.setItem(
    key,
    JSON.stringify({
      human: true,
      project_uuid: project,
      engine: recovery.engine,
      operation_id: recovery.operationId,
    }),
  );
}
export function forgetAnalysisRecovery(key: string): void {
  sessionStorage.removeItem(key);
}
