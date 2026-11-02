import type { ApprovalAction, ApprovalRecord } from "@/entities/approval";

export type ApprovalResult =
  | { kind: "ready"; items: ApprovalRecord[] }
  | { kind: "unauthorized" | "forbidden" | "conflict" | "invalid" | "unavailable"; code: string };
export type ApprovalResolution =
  | { kind: "confirmed"; item: ApprovalRecord }
  | {
      kind: "unauthorized" | "forbidden" | "conflict" | "invalid" | "unavailable" | "uncertain";
      code: string;
    };
export interface ApprovalCommandPort {
  read(projectId: string, signal: AbortSignal): Promise<ApprovalResult>;
  resolve(
    item: ApprovalRecord,
    action: ApprovalAction,
    signal: AbortSignal,
  ): Promise<ApprovalResolution>;
}
export interface ApprovalCommandContext {
  projectId: string;
  actorId: string;
  proofExpiresAt: string;
  canApprove: boolean;
  rows: readonly ApprovalRecord[];
}
type Verification = "authorized" | "unauthorized" | "forbidden" | "unavailable";
export interface ApprovalCommandOptions {
  signal: AbortSignal;
  context: () => ApprovalCommandContext | null;
  verify: (signal: AbortSignal) => Promise<Verification>;
  port: ApprovalCommandPort;
}
export type CurrentApprovalResult =
  | { kind: "confirmed" | "conflict" | "observed"; items: ApprovalRecord[] }
  | { kind: "cancelled" | "unauthorized" | "forbidden" | "invalid" | "unavailable" | "uncertain" };
