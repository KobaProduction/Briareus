/** Verified owner projection shared across workspace features; never grants authority by itself. */
import type {
  ContextProjectWire,
  ContextProjectionWire,
  ContextTeamWire,
} from "@/shared/api";

export type ProjectPermission = ContextProjectWire["permissions"][number];
export type PlatformTeamProof = ContextTeamWire;
export interface PlatformProjectProof extends ContextProjectWire {
  permissions: ProjectPermission[];
}
export interface VerifiedPlatformContext extends ContextProjectionWire {
  teams: PlatformTeamProof[];
  projects: PlatformProjectProof[];
}

/** Identity facts needed to bind a short-lived workspace proof to its provider session. */
export interface WorkspaceIdentity {
  issuer: string;
  subject: string;
  expires_at: string;
}
