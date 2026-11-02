import type { HandEffectScope } from "@/shared/lib/hand-effect-scope";
import type { FilesReadDecode } from "./read-result";
export interface FilesReadSessionReference {
  project_uuid: string;
  session_uuid: string;
  revision: number;
  status: "active" | "revoked" | "expired";
  hard_expires_at: string;
  operations: readonly string[];
  resources: readonly HandEffectScope[];
}
export type FilesReadClientResult =
  | { kind: "ready"; item: Extract<FilesReadDecode, { kind: "text" | "binary" }> }
  | { kind: "unauthorized" | "forbidden" | "invalid" | "unavailable" | "cancelled"; code: string };

export interface FilesReadCommand {
  project_uuid: string;
  agent_session_uuid: string;
  expected_grant_revision: number;
  path: string;
  max_bytes: number;
}
export interface FilesReadPort {
  selector(project: string, path: string): Promise<string>;
  read(command: FilesReadCommand, signal: AbortSignal): Promise<FilesReadClientResult>;
}
