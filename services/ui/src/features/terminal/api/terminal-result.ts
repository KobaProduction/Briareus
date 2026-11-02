/** Raw MCP content is decoded here; application ports expose only Terminal receipts. */
import { mcpValue, recordValue, requireRecord } from "@/shared/lib/transport";
import type {
  TerminalCancel,
  TerminalCreateWorkspace,
  TerminalRead,
  TerminalStart,
} from "../model/contracts";
import type {
  TerminalJobRead,
  TerminalJobState,
  TerminalJobStatus,
  TerminalReply,
  TerminalWorkspaceCreated,
} from "../model/terminal-result";

function invalid(): never {
  throw new Error("TERMINAL_OUTCOME_UNKNOWN");
}
function text(value: unknown): string {
  return typeof value === "string" ? value : invalid();
}
function flag(value: unknown): boolean {
  return typeof value === "boolean" ? value : invalid();
}
function number(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : invalid();
}
function integer(value: unknown, minimum = 0): number {
  const parsed = number(value);
  return Number.isSafeInteger(parsed) && parsed >= minimum ? parsed : invalid();
}
function optionalText(value: unknown): string | null {
  return value === null ? null : text(value);
}
function optionalInteger(value: unknown): number | null {
  return value === null ? null : integer(value, Number.MIN_SAFE_INTEGER);
}
function state(value: unknown): TerminalJobState {
  switch (value) {
    case "running":
    case "cancelling":
    case "completed":
    case "failed":
    case "cancelled":
    case "timed_out":
    case "interrupted":
    case "unknown":
      return value;
    default:
      return invalid();
  }
}
export function jobStatus(value: unknown): TerminalJobStatus {
  const row = requireRecord(value),
    id = text(row.job_id);
  if (!/^[a-f0-9]{32}$/.test(id)) return invalid();
  return {
    job_id: id,
    workspace_id: text(row.workspace_id),
    label: text(row.label),
    command: text(row.command),
    cwd: text(row.cwd),
    interactive: flag(row.interactive),
    state: state(row.state),
    pid: optionalInteger(row.pid),
    exit_code: optionalInteger(row.exit_code),
    signal: optionalInteger(row.signal),
    created_at: optionalText(row.created_at),
    started_at: optionalText(row.started_at),
    ended_at: optionalText(row.ended_at),
    duration_seconds: number(row.duration_seconds),
    output_bytes: integer(row.output_bytes),
    output_truncated: flag(row.output_truncated),
    timeout_seconds: row.timeout_seconds === null ? null : number(row.timeout_seconds),
  };
}
function receipt<Receipt>(
  value: unknown,
  decode: (value: unknown) => Receipt,
): TerminalReply<Receipt> {
  const envelope = recordValue(value);
  if (!envelope) return invalid();
  if (envelope.isError) return { kind: "failed" };
  try {
    return { kind: "accepted", receipt: mcpValue(envelope, decode) };
  } catch {
    return invalid();
  }
}
export function startedJob(
  value: unknown,
  command: TerminalStart,
): TerminalReply<TerminalJobStatus> {
  return receipt(value, (native) => {
    const job = jobStatus(native);
    if (
      job.workspace_id !== command.arguments.workspace_id ||
      job.command !== command.arguments.command
    )
      return invalid();
    return job;
  });
}
export function cancelledJob(
  value: unknown,
  command: TerminalCancel,
): TerminalReply<TerminalJobStatus> {
  return receipt(value, (native) => {
    const job = jobStatus(native);
    if (job.job_id !== command.arguments.job_id) return invalid();
    return job;
  });
}
export function createdWorkspace(
  value: unknown,
  command: TerminalCreateWorkspace,
): TerminalReply<TerminalWorkspaceCreated> {
  return receipt(value, (native) => {
    const row = requireRecord(native),
      workspace = text(row.workspace_id);
    if (workspace !== command.arguments.workspace_id) return invalid();
    return { workspace_id: workspace, path: text(row.path), created: flag(row.created) };
  });
}
export function readJob(value: unknown, command: TerminalRead): TerminalReply<TerminalJobRead> {
  return receipt(value, (native) => {
    const row = requireRecord(native);
    const read: TerminalJobRead = {
      job_id: text(row.job_id),
      cursor: integer(row.cursor),
      next_cursor: integer(row.next_cursor),
      output: text(row.output),
      total_output_bytes: integer(row.total_output_bytes),
      state: state(row.state),
      eof: flag(row.eof),
      output_truncated: flag(row.output_truncated),
    };
    // The executor samples total_output_bytes before reading a growing log;
    // next_cursor may exceed that snapshot without losing any output.
    if (
      read.job_id !== command.arguments.job_id ||
      read.cursor !== command.arguments.cursor ||
      read.next_cursor < read.cursor ||
      read.next_cursor - read.cursor > command.arguments.max_bytes
    )
      return invalid();
    return read;
  });
}
