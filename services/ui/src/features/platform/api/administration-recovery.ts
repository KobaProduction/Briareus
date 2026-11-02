import { recordValue } from "@/shared/lib/transport";
import { isUuid4 } from "@/shared/lib/uuid";
import type {
  EntityNameInput,
  EntityRenameInput,
  PlatformCommand,
  ProjectCreationInput,
  TeamMemberInput,
} from "../model/administration-contracts";

function exactFields(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return (
    Object.keys(value).length === keys.length && keys.every((key) => Object.hasOwn(value, key))
  );
}

function entityName(value: unknown): value is EntityNameInput {
  const row = recordValue(value);
  return !!row && exactFields(row, ["name"]) && typeof row.name === "string";
}

function entityRename(value: unknown): value is EntityRenameInput {
  const row = recordValue(value);
  return (
    !!row &&
    exactFields(row, ["id", "name", "expected_name"]) &&
    isUuid4(row.id) &&
    typeof row.name === "string" &&
    typeof row.expected_name === "string"
  );
}

function projectCreation(value: unknown): value is ProjectCreationInput {
  const row = recordValue(value);
  return (
    !!row &&
    exactFields(row, ["name", "team_id"]) &&
    typeof row.name === "string" &&
    (row.team_id === null || isUuid4(row.team_id))
  );
}

function teamMember(value: unknown): value is TeamMemberInput {
  const row = recordValue(value);
  return !!row && exactFields(row, ["id", "user_id"]) && isUuid4(row.id) && isUuid4(row.user_id);
}

function pendingCommand(value: unknown): PlatformCommand | null {
  const row = recordValue(value);
  if (
    !row ||
    !exactFields(row, ["operation_uuid", "action", "data"]) ||
    !isUuid4(row.operation_uuid)
  ) {
    return null;
  }
  const operation_uuid = row.operation_uuid,
    data = row.data;
  switch (row.action) {
    case "team.create":
      return entityName(data) ? { operation_uuid, action: row.action, data } : null;
    case "team.rename":
    case "project.rename":
      return entityRename(data) ? { operation_uuid, action: row.action, data } : null;
    case "project.create":
      return projectCreation(data) ? { operation_uuid, action: row.action, data } : null;
    case "team.member.add":
    case "team.member.remove":
      return teamMember(data) ? { operation_uuid, action: row.action, data } : null;
    default:
      return null;
  }
}

const storageKey = (actor: string) => `briareus:platform-command:${actor}`;

export function readPendingAdministration(actor: string): PlatformCommand | null {
  try {
    return pendingCommand(JSON.parse(sessionStorage.getItem(storageKey(actor)) ?? "null"));
  } catch {
    return null;
  }
}

export function storePendingAdministration(actor: string, command: PlatformCommand | null): void {
  try {
    if (command) sessionStorage.setItem(storageKey(actor), JSON.stringify(command));
    else sessionStorage.removeItem(storageKey(actor));
  } catch {
    /* The caller retains its exact in-memory command. */
  }
}
