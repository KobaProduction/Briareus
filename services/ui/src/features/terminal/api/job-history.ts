import { eventBus } from "@/shared/events";
import { mcpValue, requireRecord } from "@/shared/lib/transport";
import type { TerminalJobHistory } from "../model/job-history";
import { jobStatus } from "./terminal-result";

export function decodeJobHistory(value: unknown): TerminalJobHistory {
  return mcpValue(value, (native) => {
    const row = requireRecord(native);
    if (
      !Array.isArray(row.jobs) ||
      row.jobs.length > 50 ||
      row.count !== row.jobs.length ||
      !Number.isSafeInteger(row.total) ||
      typeof row.total !== "number" ||
      row.total < row.count ||
      row.offset !== 0 ||
      row.limit !== 50 ||
      typeof row.truncated !== "boolean"
    )
      throw new Error("TERMINAL_HISTORY_INVALID");
    const jobs = row.jobs.map(jobStatus);
    if (jobs.some((job) => job.workspace_id !== "default"))
      throw new Error("TERMINAL_HISTORY_INVALID");
    if (new Set(jobs.map((job) => job.job_id)).size !== jobs.length)
      throw new Error("TERMINAL_HISTORY_INVALID");
    return { jobs, total: row.total, truncated: row.truncated };
  });
}

export function terminalJobHistory(
  project: string,
  signal: AbortSignal,
): Promise<TerminalJobHistory> {
  return eventBus.request(
    "terminal.command",
    {
      project_uuid: project,
      operation_uuid: crypto.randomUUID(),
      tool: "job_list",
      arguments: { workspace_id: "default", offset: 0, limit: 50 },
    },
    decodeJobHistory,
    signal,
  );
}
