import { RpcError } from "@/shared/events";
import type { TerminalCreateWorkspace, TerminalPorts, TerminalStart } from "./contracts";
import { acceptedTerminalReceipt, type TerminalJobState } from "./terminal-result";

interface JobRun {
  intent: TerminalStart;
  recovering: boolean;
  jobId: string;
  signal: AbortSignal;
  current: () => boolean;
  started: (id: string) => void;
  output: (text: string) => void;
}
export type TerminalRunResult =
  | { kind: "complete"; state: TerminalJobState }
  | { kind: "superseded" };
async function prepareWorkspace(run: JobRun, port: TerminalPorts["command"]): Promise<boolean> {
  const command: TerminalCreateWorkspace = {
    project_uuid: run.intent.project_uuid,
    operation_uuid: crypto.randomUUID(),
    tool: "workspace_create",
    arguments: { workspace_id: "default" },
  };
  while (run.current() && !run.signal.aborted) {
    try {
      const workspace = await port(command, run.signal);
      if (!run.current()) return false;
      acceptedTerminalReceipt(workspace);
      return true;
    } catch (error) {
      if (
        !(
          error instanceof RpcError &&
          error.message === "TERMINAL_PREPARING" &&
          error.uncertaintyDeclared &&
          error.uncertain === false
        )
      )
        throw error;
      await new Promise<void>((resolve) => setTimeout(resolve, 1000));
    }
  }
  return false;
}
async function startJob(run: JobRun, port: TerminalPorts["command"]): Promise<string | null> {
  if (run.jobId) return run.jobId;
  if (!run.recovering && !(await prepareWorkspace(run, port))) return null;
  const result = await port(run.intent, run.signal);
  if (!run.current()) return null;
  const id = acceptedTerminalReceipt(result).job_id;
  run.started(id);
  return id;
}
export async function runTerminalJob(
  run: JobRun,
  port: TerminalPorts["command"],
): Promise<TerminalRunResult> {
  const jobId = await startJob(run, port);
  if (jobId === null || !run.current()) return { kind: "superseded" };
  let cursor = 0,
    output = "";
  run.output("");
  while (run.current()) {
    const raw = await port(
      {
        ...run.intent,
        operation_uuid: crypto.randomUUID(),
        tool: "job_read",
        arguments: { job_id: jobId, cursor, max_bytes: 65536, wait_seconds: 0 },
      },
      run.signal,
    );
    if (!run.current()) return { kind: "superseded" };
    const result = acceptedTerminalReceipt(raw);
    output = (output + result.output).slice(-1048576);
    run.output(output);
    cursor = result.next_cursor;
    if (result.eof) return { kind: "complete", state: result.state };
    // Preserve existing bounded job-output cadence; no new background polling.
    await new Promise<void>((resolve) => setTimeout(resolve, 1000));
  }
  return { kind: "superseded" };
}
