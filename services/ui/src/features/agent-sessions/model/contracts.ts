import type { CurrentAgentSession, NormalSession } from "@/entities/agent-session";
import type { PreparedNormalSessionOpen } from "./open-intent";

export type NormalSessionResult =
  | { kind: "created"; session: NormalSession }
  | {
      kind: "unauthorized" | "forbidden" | "conflict" | "invalid" | "unavailable" | "uncertain";
      code: string;
    };
export type SessionInventory =
  | { kind: "ready"; items: CurrentAgentSession[] }
  | { kind: "unauthorized" | "forbidden" | "conflict" | "invalid" | "unavailable"; code: string };
export type CurrentSessionRead =
  | { kind: "ready"; item: CurrentAgentSession }
  | { kind: "not_found"; code: "AGENT_SESSION_NOT_FOUND" }
  | { kind: "unauthorized" | "forbidden" | "conflict" | "invalid" | "unavailable"; code: string };
export type SessionRevokeResult =
  | { kind: "confirmed"; session_uuid: string; project_uuid: string; revision: number }
  | {
      kind: "unauthorized" | "forbidden" | "conflict" | "invalid" | "unavailable" | "uncertain";
      code: string;
    };
export interface SessionCommandPort {
  list(
    projectId: string,
    actorId: string,
    canApprove: boolean,
    signal: AbortSignal,
  ): Promise<SessionInventory>;
  read(
    projectId: string,
    sessionId: string,
    actorId: string,
    canApprove: boolean,
    signal: AbortSignal,
  ): Promise<CurrentSessionRead>;
  revoke(session: CurrentAgentSession, signal: AbortSignal): Promise<SessionRevokeResult>;
  executeOpen(
    command: PreparedNormalSessionOpen,
    signal: AbortSignal,
  ): Promise<NormalSessionResult>;
}
