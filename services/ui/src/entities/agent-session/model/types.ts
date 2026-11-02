import type { HandEffectScope } from "@/shared/lib/hand-effect-scope";

export type ElevationPolicy = "fixed" | "requestable";
export type SessionStatus = "active" | "expired" | "revoked";
export type SessionScope = HandEffectScope;
export interface CurrentAgentSession {
  session_uuid: string;
  project_uuid: string;
  label?: string | null;
  created_at?: string | null;
  created_by_user_uuid: string;
  revision: number;
  status: SessionStatus;
  is_elevated: boolean;
  elevation_policy: ElevationPolicy;
  hard_expires_at: string;
  operations: string[];
  resources: SessionScope[];
  allowed_actions: "revoke"[];
}
export interface NormalSession {
  session_uuid: string;
  project_uuid: string;
  revision: 1;
  status: "active";
  is_elevated: false;
  elevation_policy: ElevationPolicy;
  hard_expires_at: string;
  operations: ["files.read", "project.metadata.read"];
  resources: [];
}
