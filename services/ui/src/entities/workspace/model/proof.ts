/** Verified owner projection shared across workspace features; never grants authority by itself. */
export type ProjectPermission = "use_resources" | "approve_agent_session"
export interface PlatformTeamProof { id: string; owner: boolean; name?:string|null; member?:boolean }
export interface PlatformProjectProof {
  id: string
  name?:string|null
  owner: {kind:"user" | "team";id:string}
  permissions: ProjectPermission[]
}
export interface VerifiedPlatformContext {
  directory_paged?:boolean
  authenticated: true
  authority: "platform"
  rauthy: { issuer: string; subject: string }
  user: {id:string;role:"user" | "operator";enabled:true;name?:string|null;email?:string|null}
  teams: PlatformTeamProof[]
  projects: PlatformProjectProof[]
  expires_at: string
}
