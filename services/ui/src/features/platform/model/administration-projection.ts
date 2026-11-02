import type { ManagedProject } from "@/entities/project";
import type { ManagedTeam } from "@/entities/team";
import type { PlatformPerson } from "@/entities/user";
import { recordValue, requireRecord } from "@/shared/lib/transport";
import { isUuid4 } from "@/shared/lib/uuid";
import type { PlatformInventory } from "./administration-contracts";

function uuid(value: unknown): string {
  if (!isUuid4(value)) throw new Error("PLATFORM_INVENTORY_INVALID");
  return value;
}
function textOrNull(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}
function uuidList(value: unknown): string[] {
  if (!Array.isArray(value)) throw new Error("PLATFORM_INVENTORY_INVALID");
  const result = value.map((item: unknown) => uuid(item));
  if (new Set(result).size !== result.length) throw new Error("PLATFORM_INVENTORY_INVALID");
  return result;
}
function person(value: unknown): PlatformPerson {
  const row = requireRecord(value);
  if (!textOrNull(row.name) || !textOrNull(row.email) || typeof row.enabled !== "boolean")
    throw new Error("PLATFORM_INVENTORY_INVALID");
  const role = row.role;
  if (role !== "user" && role !== "operator") throw new Error("PLATFORM_INVENTORY_INVALID");
  return { id: uuid(row.id), name: row.name, email: row.email, role, enabled: row.enabled };
}
function team(value: unknown): ManagedTeam {
  const row = requireRecord(value);
  if (typeof row.name !== "string") throw new Error("PLATFORM_INVENTORY_INVALID");
  return {
    id: uuid(row.id),
    name: row.name,
    owner_user_id: uuid(row.owner_user_id),
    member_ids: uuidList(row.member_ids),
  };
}
function project(value: unknown): ManagedProject {
  const row = requireRecord(value);
  if (
    typeof row.name !== "string" ||
    !textOrNull(row.owner_user_id) ||
    !textOrNull(row.owner_team_id)
  )
    throw new Error("PLATFORM_INVENTORY_INVALID");
  const user = row.owner_user_id,
    owner = row.owner_team_id;
  if ((user === null) === (owner === null)) throw new Error("PLATFORM_INVENTORY_INVALID");
  return {
    id: uuid(row.id),
    name: row.name,
    owner_user_id: user === null ? null : uuid(user),
    owner_team_id: owner === null ? null : uuid(owner),
  };
}
function inventoryRows<T extends { id: string }>(
  value: unknown,
  decode: (value: unknown) => T,
): T[] {
  if (!Array.isArray(value) || value.length > 100) throw new Error("PLATFORM_INVENTORY_INVALID");
  const rows = value.map((item: unknown) => decode(item));
  if (new Set(rows.map((row) => row.id)).size !== rows.length)
    throw new Error("PLATFORM_INVENTORY_INVALID");
  return rows;
}
export function decodePlatformInventory(value: unknown): PlatformInventory {
  const row = recordValue(value);
  if (!row || typeof row.truncated !== "boolean") throw new Error("PLATFORM_INVENTORY_INVALID");
  return {
    users: inventoryRows(row.users, person),
    teams: inventoryRows(row.teams, team),
    projects: inventoryRows(row.projects, project),
    truncated: row.truncated,
  };
}
