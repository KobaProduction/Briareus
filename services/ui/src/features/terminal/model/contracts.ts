import type { HandEffectScope } from "@/shared/lib/hand-effect-scope";
import type { TerminalJobHistory } from "./job-history";
import type {
  TerminalJobRead,
  TerminalJobStatus,
  TerminalReply,
  TerminalWorkspaceCreated,
} from "./terminal-result";

export interface TerminalAuthority {
  project_uuid: string;
  operation_uuid: string;
}
export interface TerminalStart extends TerminalAuthority {
  tool: "job_start";
  arguments: { workspace_id: "default"; command: string; interactive: false };
}
export interface TerminalCreateWorkspace extends TerminalAuthority {
  tool: "workspace_create";
  arguments: { workspace_id: "default" };
}
export interface TerminalRead extends TerminalAuthority {
  tool: "job_read";
  arguments: { job_id: string; cursor: number; max_bytes: 65536; wait_seconds: 0 };
}
export interface TerminalCancel extends TerminalAuthority {
  tool: "job_cancel";
  arguments: { job_id: string; grace_seconds: 0.5 };
}
export type TerminalCommand =
  | TerminalStart
  | TerminalCreateWorkspace
  | TerminalRead
  | TerminalCancel;
export interface TerminalCommandPort {
  (command: TerminalStart, signal?: AbortSignal): Promise<TerminalReply<TerminalJobStatus>>;
  (
    command: TerminalCreateWorkspace,
    signal?: AbortSignal,
  ): Promise<TerminalReply<TerminalWorkspaceCreated>>;
  (command: TerminalRead, signal?: AbortSignal): Promise<TerminalReply<TerminalJobRead>>;
  (command: TerminalCancel, signal?: AbortSignal): Promise<TerminalReply<TerminalJobStatus>>;
}
export interface TerminalRecovery {
  intent: TerminalStart;
  jobId: string;
}
export interface TerminalPorts {
  history?(project: string, signal: AbortSignal): Promise<TerminalJobHistory>;
  resources(project: string, signal: AbortSignal): Promise<HandEffectScope[]>;
  command: TerminalCommandPort;
  restore(key: string, project: string | null): TerminalRecovery | null;
  save(key: string, intent: TerminalStart, jobId?: string): void;
  forget(key: string): void;
}
