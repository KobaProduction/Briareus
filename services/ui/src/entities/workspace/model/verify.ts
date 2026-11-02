import { isUuid4 } from "@/shared/lib/uuid";
import type {
  PlatformProjectProof,
  PlatformTeamProof,
  ProjectPermission,
  VerifiedPlatformContext,
  WorkspaceIdentity,
} from "./proof";

type WorkspaceUser = VerifiedPlatformContext["user"];
function object(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
function validName(value: unknown): value is string | null | undefined {
  return (
    value === undefined || value === null || (typeof value === "string" && value.length <= 255)
  );
}
function userProof(value: unknown): WorkspaceUser | null {
  const row = object(value);
  if (
    !row ||
    !isUuid4(row.id) ||
    row.enabled !== true ||
    (row.role !== "user" && row.role !== "operator")
  )
    return null;
  return {
    id: row.id,
    role: row.role,
    enabled: true,
    name: typeof row.name === "string" ? row.name : undefined,
    email: typeof row.email === "string" ? row.email : undefined,
  };
}
function teamProof(value: unknown, user: WorkspaceUser): PlatformTeamProof | null {
  const row = object(value);
  if (!row || !isUuid4(row.id) || typeof row.owner !== "boolean" || !validName(row.name))
    return null;
  if (row.member !== undefined && typeof row.member !== "boolean") return null;
  if (row.member === false && user.role !== "operator") return null;
  return { id: row.id, owner: row.owner, name: row.name, member: row.member !== false };
}
function teamProofs(values: unknown[], user: WorkspaceUser): PlatformTeamProof[] | null {
  const teams: PlatformTeamProof[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const team = teamProof(value, user);
    if (!team || seen.has(team.id)) return null;
    seen.add(team.id);
    teams.push(team);
  }
  return teams;
}
function permissions(value: unknown): ProjectPermission[] | null {
  if (!Array.isArray(value) || value.length > 2 || new Set(value).size !== value.length)
    return null;
  const result: ProjectPermission[] = [];
  for (const permission of value) {
    if (permission !== "use_resources" && permission !== "approve_agent_session") return null;
    result.push(permission);
  }
  return result;
}
function projectOwner(
  value: unknown,
  user: WorkspaceUser,
  teams: PlatformTeamProof[],
): PlatformProjectProof["owner"] | null {
  const owner = object(value);
  if (!owner || !isUuid4(owner.id) || (owner.kind !== "user" && owner.kind !== "team")) return null;
  if (owner.kind === "user" && owner.id !== user.id && user.role !== "operator") return null;
  if (owner.kind === "team" && !teams.some((team) => team.id === owner.id)) return null;
  return { kind: owner.kind, id: owner.id };
}
function canApprove(
  owner: PlatformProjectProof["owner"],
  user: WorkspaceUser,
  teams: PlatformTeamProof[],
): boolean {
  if (user.role === "operator") return true;
  if (owner.kind === "user") return owner.id === user.id;
  return teams.some((team) => team.id === owner.id && team.owner);
}
function projectProof(
  value: unknown,
  user: WorkspaceUser,
  teams: PlatformTeamProof[],
): PlatformProjectProof | null {
  const row = object(value);
  if (!row || !isUuid4(row.id) || !validName(row.name)) return null;
  const owner = projectOwner(row.owner, user, teams);
  const grants = permissions(row.permissions);
  if (!owner || !grants) return null;
  if (grants.includes("approve_agent_session") && !canApprove(owner, user, teams)) return null;
  return { id: row.id, name: row.name, owner, permissions: grants };
}
function projectProofs(
  values: unknown[],
  user: WorkspaceUser,
  teams: PlatformTeamProof[],
): PlatformProjectProof[] | null {
  const projects: PlatformProjectProof[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const project = projectProof(value, user, teams);
    if (!project || seen.has(project.id)) return null;
    seen.add(project.id);
    projects.push(project);
  }
  return projects;
}
function validLifetime(value: unknown, identity: WorkspaceIdentity): value is string {
  if (typeof value !== "string" || !/(?:Z|[+-][0-2][0-9]:[0-5][0-9])$/.test(value)) return false;
  const expires = Date.parse(value);
  return (
    Number.isFinite(expires) &&
    expires > Date.now() &&
    expires <= Date.now() + 31000 &&
    expires <= Date.parse(identity.expires_at)
  );
}
function proofRows(value: unknown): value is unknown[] {
  return Array.isArray(value) && value.length <= 100;
}
export interface WorkspaceDirectoryRows {
  teams: PlatformTeamProof[];
  projects: PlatformProjectProof[];
}
/** A page is bounded independently of the complete verified directory.
 * Project ownership is checked against all teams already read in this snapshot. */
export function decodeDirectoryRows(
  kind: "teams" | "projects",
  values: unknown,
  context: VerifiedPlatformContext,
  identity: WorkspaceIdentity,
): WorkspaceDirectoryRows | null {
  if (!proofRows(values) || !validLifetime(context.expires_at, identity)) return null;
  if (context.rauthy.issuer !== identity.issuer || context.rauthy.subject !== identity.subject)
    return null;
  if (kind === "teams") {
    const teams = teamProofs(values, context.user);
    return teams ? { teams, projects: [] } : null;
  }
  const projects = projectProofs(values, context.user, context.teams);
  return projects ? { teams: [], projects } : null;
}
/** Decode a bounded, current owner projection; identity alone never grants access. */
export function validatePlatformContext(
  value: unknown,
  identity: WorkspaceIdentity,
): VerifiedPlatformContext | null {
  const row = object(value);
  if (row?.authenticated !== true || row.authority !== "platform") return null;
  const provider = object(row.rauthy);
  if (!provider || provider.subject !== identity.subject || provider.issuer !== identity.issuer)
    return null;
  if (!proofRows(row.teams) || !proofRows(row.projects) || !validLifetime(row.expires_at, identity))
    return null;
  const user = userProof(row.user);
  if (!user) return null;
  const teams = teamProofs(row.teams, user);
  if (!teams) return null;
  const projects = projectProofs(row.projects, user, teams);
  if (!projects) return null;
  return {
    directory_paged: row.directory_paged === true,
    authenticated: true,
    authority: "platform",
    rauthy: { issuer: identity.issuer, subject: identity.subject },
    user,
    teams,
    projects,
    expires_at: row.expires_at,
  };
}
