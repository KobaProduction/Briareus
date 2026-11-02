/** Native Terminal receipts; identifiers retain the executor's existing wire format. */
export type TerminalJobState =
  | "running"
  | "cancelling"
  | "completed"
  | "failed"
  | "cancelled"
  | "timed_out"
  | "interrupted"
  | "unknown";

export interface TerminalWorkspaceCreated {
  workspace_id: string;
  path: string;
  created: boolean;
}
export interface TerminalJobStatus {
  job_id: string;
  workspace_id: string;
  label: string;
  command: string;
  cwd: string;
  interactive: boolean;
  state: TerminalJobState;
  pid: number | null;
  exit_code: number | null;
  signal: number | null;
  created_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number;
  output_bytes: number;
  output_truncated: boolean;
  timeout_seconds: number | null;
}
export interface TerminalJobRead {
  job_id: string;
  cursor: number;
  next_cursor: number;
  output: string;
  total_output_bytes: number;
  state: TerminalJobState;
  eof: boolean;
  output_truncated: boolean;
}
export type TerminalReply<Receipt> = { kind: "accepted"; receipt: Receipt } | { kind: "failed" };

export function acceptedTerminalReceipt<Receipt>(reply: TerminalReply<Receipt>): Receipt {
  if (reply.kind === "failed") throw new Error("TERMINAL_OPERATION_FAILED");
  return reply.receipt;
}
