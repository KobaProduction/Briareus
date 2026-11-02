import { requireRecord } from "../lib/transport";
import type {
  ContextIdentityWire,
  ContextProjectWire,
  ContextProjectionWire,
  ContextSnapshotData,
  ContextTeamWire,
} from "../api";
import { flag, list, literal, optionalText, text } from "./wire-values";

function role(value: unknown): "user" | "operator" {
  if (value !== "user" && value !== "operator") throw Error("Invalid context role");
  return value;
}
function permission(value: unknown): "use_resources" | "approve_agent_session" {
  if (value !== "use_resources" && value !== "approve_agent_session")
    throw Error("Invalid context permission");
  return value;
}
function ownerKind(value: unknown): "user" | "team" {
  if (value !== "user" && value !== "team") throw Error("Invalid context owner");
  return value;
}
function team(value: unknown): ContextTeamWire {
  const row = requireRecord(value);
  return {
    id: text(row, "id"),
    owner: flag(row, "owner"),
    name: optionalText(row, "name"),
    member: row.member === undefined ? undefined : flag(row, "member"),
  };
}
function project(value: unknown): ContextProjectWire {
  const row = requireRecord(value),
    owner = requireRecord(row.owner);
  return {
    id: text(row, "id"),
    name: optionalText(row, "name"),
    owner: { kind: ownerKind(owner.kind), id: text(owner, "id") },
    permissions: list(row.permissions, permission),
  };
}
function context(value: unknown): ContextProjectionWire {
  const row = requireRecord(value),
    subject = requireRecord(row.rauthy),
    user = requireRecord(row.user);
  return {
    authenticated: literal(row, "authenticated", true),
    authority: literal(row, "authority", "platform"),
    directory_paged: row.directory_paged === undefined ? undefined : flag(row, "directory_paged"),
    rauthy: { issuer: text(subject, "issuer"), subject: text(subject, "subject") },
    user: {
      id: text(user, "id"),
      role: role(user.role),
      enabled: literal(user, "enabled", true),
      name: optionalText(user, "name"),
      email: optionalText(user, "email"),
    },
    teams: list(row.teams, team),
    projects: list(row.projects, project),
    expires_at: text(row, "expires_at"),
  };
}
function identity(value: unknown): ContextIdentityWire {
  const row = requireRecord(value);
  return {
    authenticated: literal(row, "authenticated", true),
    authority: literal(row, "authority", "rauthy"),
    issuer: text(row, "issuer"),
    subject: text(row, "subject"),
    client_id: text(row, "client_id"),
    expires_at: text(row, "expires_at"),
    platform_membership_verified: literal(row, "platform_membership_verified", false),
    permissions: list(row.permissions, (value) => {
      if (typeof value !== "string") throw Error("Invalid identity permission");
      return value;
    }),
  };
}
/** Structural decoding only. The owning workspace still verifies provider binding,
 * lifetime, memberships, permission inheritance and the focused project. */
export function contextSnapshot(value: unknown): ContextSnapshotData {
  const row = requireRecord(value);
  return { context: context(row.context), identity: identity(row.identity) };
}
