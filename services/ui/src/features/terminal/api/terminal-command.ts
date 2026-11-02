import { eventBus } from "@/shared/events";
import { parseHandEffectScopes } from "@/shared/lib/hand-effect-scope";
import { recordValue } from "@/shared/lib/transport";
import type {
  TerminalCancel,
  TerminalCommand,
  TerminalCreateWorkspace,
  TerminalRead,
  TerminalStart,
} from "../model/contracts";
import type {
  TerminalJobRead,
  TerminalJobStatus,
  TerminalReply,
  TerminalWorkspaceCreated,
} from "../model/terminal-result";
import { cancelledJob, createdWorkspace, readJob, startedJob } from "./terminal-result";

export function terminalCommand(
  command: TerminalStart,
  signal?: AbortSignal,
): Promise<TerminalReply<TerminalJobStatus>>;
export function terminalCommand(
  command: TerminalCreateWorkspace,
  signal?: AbortSignal,
): Promise<TerminalReply<TerminalWorkspaceCreated>>;
export function terminalCommand(
  command: TerminalRead,
  signal?: AbortSignal,
): Promise<TerminalReply<TerminalJobRead>>;
export function terminalCommand(
  command: TerminalCancel,
  signal?: AbortSignal,
): Promise<TerminalReply<TerminalJobStatus>>;
export async function terminalCommand(
  command: TerminalCommand,
  signal?: AbortSignal,
): Promise<TerminalReply<TerminalJobStatus | TerminalJobRead | TerminalWorkspaceCreated>> {
  return eventBus.request(
    "terminal.command",
    {
      project_uuid: command.project_uuid,
      operation_uuid: command.operation_uuid,
      tool: command.tool,
      arguments: command.arguments,
    },
    (raw) => {
      switch (command.tool) {
        case "workspace_create":
          return createdWorkspace(raw, command);
        case "job_start":
          return startedJob(raw, command);
        case "job_read":
          return readJob(raw, command);
        case "job_cancel":
          return cancelledJob(raw, command);
      }
    },
    signal,
  );
}
export async function terminalResources(project: string, signal: AbortSignal) {
  return eventBus.request(
    "terminal.resources",
    { project_uuid: project },
    (value) => {
      const raw = recordValue(value);
      const scopes = parseHandEffectScopes(raw?.items, ["terminal.execute"], project);
      if (!scopes || scopes.some((item) => item.hand !== "terminal"))
        throw new Error("RUNTIME_SCOPE_INVALID");
      return scopes;
    },
    signal,
  );
}
