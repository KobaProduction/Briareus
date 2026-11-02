import type { ManagedNode } from "@/entities/node";
import {
  replyArray,
  replyBoolean,
  replyBudget,
  replyChoice,
  replyInstant,
  replyNumber,
  replyRecord,
  replyString,
  replyUuid,
} from "./node-reply-values";
function managedNode(value: unknown): ManagedNode {
  const node = replyRecord(value),
    scope = replyChoice(node.scope, ["personal", "team", "shared"]),
    owner = node.owner_uuid === null ? null : replyUuid(node.owner_uuid);
  if ((scope === "shared") !== (owner === null)) throw Error("NODE_RESPONSE_INVALID");
  return {
    id: replyUuid(node.id),
    name: replyString(node.name, 128),
    scope,
    owner_uuid: owner,
    host_uuid: replyUuid(node.host_uuid),
    runtime_uid: replyNumber(node.runtime_uid, 2000, 2 ** 31 - 1),
    endpoint: replyString(node.endpoint),
    budget: replyBudget(node.budget),
    enabled: replyBoolean(node.enabled),
    paired: replyBoolean(node.paired),
    sequence: replyNumber(node.sequence, 1),
    last_seen_at: node.last_seen_at === null ? null : replyInstant(node.last_seen_at),
    created_at: replyInstant(node.created_at),
  };
}
export function decodeNodeInventory(value: unknown): ManagedNode[] {
  const result = replyRecord(value);
  replyBoolean(result.truncated);
  return replyArray(result.items, managedNode);
}
