/** Unverified, public Panel context transport shapes; entity validators own trust. */
export interface ContextTeamWire {
  id: string;
  owner: boolean;
  name?: string | null;
  member?: boolean;
}
export interface ContextProjectWire {
  id: string;
  name?: string | null;
  owner: { kind: "user" | "team"; id: string };
  permissions: readonly ("use_resources" | "approve_agent_session")[];
}
export interface ContextProjectionWire {
  authenticated: true;
  authority: "platform";
  directory_paged?: boolean;
  rauthy: { issuer: string; subject: string };
  user: {
    id: string;
    role: "user" | "operator";
    enabled: true;
    name?: string | null;
    email?: string | null;
  };
  teams: readonly ContextTeamWire[];
  projects: readonly ContextProjectWire[];
  expires_at: string;
}
export interface ContextIdentityWire {
  authenticated: true;
  authority: "rauthy";
  issuer: string;
  subject: string;
  client_id: string;
  expires_at: string;
  platform_membership_verified: false;
  permissions: readonly string[];
}
export interface ContextSnapshotData {
  context: ContextProjectionWire;
  identity: ContextIdentityWire;
}
