import type {
  ScopeSelection,
  SourceCommandBinding,
  SourceCommandTarget,
  ResourceOwner,
} from "./contracts";
import { canonicalUuid4 } from "./contracts";
import {
  BFF_OWNERS,
  type BffOwner,
  type BffOwnerEvidence,
  type BffOwnerState,
  type BffEffectEvidence,
  type BffOwnerEffect,
  type OwnerEffectPhase,
} from "./bff-evidence";

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw Error("Invalid BFF evidence record");
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== "string") throw Error("Invalid BFF evidence text");
  return value;
}
function uuid(value: unknown): string {
  const result = text(value);
  if (!canonicalUuid4(result)) throw Error("Invalid BFF evidence UUID");
  return result;
}
function exact(value: Record<string, unknown>, keys: readonly string[]): void {
  if (Object.keys(value).length !== keys.length || !keys.every((key) => Object.hasOwn(value, key)))
    throw Error("Invalid BFF evidence shape");
}
function scope(value: unknown): ScopeSelection {
  const item = record(value);
  switch (item.kind) {
    case "account":
    case "operator":
      exact(item, ["kind"]);
      return { kind: item.kind };
    case "team":
      exact(item, ["kind", "teamId"]);
      return { kind: "team", teamId: uuid(item.teamId) };
    case "project":
      exact(item, ["kind", "projectId"]);
      return { kind: "project", projectId: uuid(item.projectId) };
    default:
      throw Error("Invalid BFF evidence scope");
  }
}
function resourceOwner(value: unknown): ResourceOwner {
  const owner = scope(value);
  if (owner.kind !== "project" && owner.kind !== "team") throw Error("Invalid BFF resource owner");
  return owner;
}
function target(value: unknown): SourceCommandTarget {
  const item = record(value),
    id = uuid(item.id);
  switch (item.kind) {
    case "project":
    case "team":
    case "project_resource":
      exact(item, ["kind", "id"]);
      return { kind: item.kind, id };
    case "resource":
      exact(item, ["kind", "id", "owner"]);
      return { kind: "resource", id, owner: resourceOwner(item.owner) };
    default:
      throw Error("Invalid BFF effect target");
  }
}
function binding(value: unknown): SourceCommandBinding {
  const item = record(value);
  return { operation: text(item.operation), target: target(item.target) };
}
function effectPhase(value: unknown): OwnerEffectPhase {
  switch (value) {
    case "pending":
    case "unknown":
    case "reconciling":
    case "confirmed":
    case "denied":
      return value;
    default:
      throw Error("Invalid BFF effect phase");
  }
}
function ownerState(value: unknown): BffOwnerState {
  const item = record(value),
    revision = item.revision === null ? null : text(item.revision);
  switch (item.availability) {
    case "ready":
    case "upgrading":
    case "unavailable":
    case "unknown":
      return { availability: item.availability, revision };
    default:
      throw Error("Invalid BFF owner availability");
  }
}
function ownerStates(value: unknown): Record<BffOwner, BffOwnerState> {
  const item = record(value);
  exact(item, BFF_OWNERS);
  return {
    identity: ownerState(item.identity),
    access: ownerState(item.access),
    control: ownerState(item.control),
    catalog: ownerState(item.catalog),
  };
}
function ownerEffects(value: unknown): Partial<Record<BffOwner, BffOwnerEffect>> {
  const item = record(value),
    effects: Partial<Record<BffOwner, BffOwnerEffect>> = {};
  if (Object.keys(item).some((key) => !BFF_OWNERS.some((owner) => owner === key)))
    throw Error("Invalid BFF effect owner");
  for (const owner of BFF_OWNERS) {
    if (!Object.hasOwn(item, owner)) continue;
    const effect = record(item[owner]);
    effects[owner] = { phase: effectPhase(effect.phase), revision: text(effect.revision) };
  }
  return effects;
}
export function decodeBffOwnerEvidence(value: unknown): BffOwnerEvidence | null {
  try {
    const item = record(value);
    return {
      actorUserId: text(item.actorUserId),
      scope: scope(item.scope),
      observedAtUtc: text(item.observedAtUtc),
      expiresAtUtc: text(item.expiresAtUtc),
      owners: ownerStates(item.owners),
    };
  } catch {
    return null;
  }
}
export function decodeBffEffectEvidence(value: unknown): BffEffectEvidence | null {
  try {
    const item = record(value);
    return {
      actorUserId: text(item.actorUserId),
      scope: scope(item.scope),
      binding: binding(item.binding),
      idempotencyKey: text(item.idempotencyKey),
      operationUuid: text(item.operationUuid),
      phase: effectPhase(item.phase),
      owners: ownerEffects(item.owners),
      observedAtUtc: text(item.observedAtUtc),
    };
  } catch {
    return null;
  }
}
