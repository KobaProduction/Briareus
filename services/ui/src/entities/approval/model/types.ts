import type { HandEffectScope } from "@/shared/lib/hand-effect-scope";

export type ApprovalStatus = "pending" | "approved" | "rejected";
export type ApprovalAction = "approve" | "deny";
export type ScopedEffect = HandEffectScope;
export interface ApprovalRecord {
  id: string;
  project_uuid: string;
  agent_session_uuid: string;
  label?: string | null;
  created_at?: string | null;
  requested_by_user_uuid: string;
  status: ApprovalStatus;
  version: number;
  requested_operations: string[];
  requested_resources: ScopedEffect[];
  requested_expires_at: string;
  resolved_by_user_uuid: string | null;
  issued_session_uuid: string | null;
  allowed_actions: ApprovalAction[];
}
