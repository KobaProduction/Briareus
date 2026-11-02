import { isUuid4 } from "@/shared/lib/uuid";
import type { ResourceLimits, ManagedNode } from "@/entities/node";
export function replyRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw Error("NODE_RESPONSE_INVALID");
  return value as Record<string, unknown>;
}
export function replyString(value: unknown, max = 2048): string {
  if (typeof value !== "string" || value.length > max) throw Error("NODE_RESPONSE_INVALID");
  return value;
}
export function replyBoolean(value: unknown): boolean {
  if (typeof value !== "boolean") throw Error("NODE_RESPONSE_INVALID");
  return value;
}
export function replyNumber(
  value: unknown,
  min: number,
  max = Number.MAX_SAFE_INTEGER,
  integer = true,
): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < min ||
    value > max ||
    (integer && !Number.isSafeInteger(value))
  )
    throw Error("NODE_RESPONSE_INVALID");
  return value;
}
export function replyUuid(value: unknown): string {
  if (!isUuid4(value)) throw Error("NODE_RESPONSE_INVALID");
  return value;
}
export function replyInstant(value: unknown): string {
  const instant = replyString(value, 64);
  if (!/(Z|[+-]\d{2}:\d{2})$/.test(instant) || !Number.isFinite(Date.parse(instant)))
    throw Error("NODE_RESPONSE_INVALID");
  return instant;
}
export function replyChoice<const Values extends readonly string[]>(
  value: unknown,
  choices: Values,
): Values[number] {
  const found = choices.find((choice) => choice === value);
  if (found === undefined) throw Error("NODE_RESPONSE_INVALID");
  return found;
}
export function replyArray<T>(value: unknown, decode: (item: unknown) => T, max = 100): T[] {
  if (!Array.isArray(value) || value.length > max) throw Error("NODE_RESPONSE_INVALID");
  return value.map(decode);
}
export function replyLimits(value: unknown): ResourceLimits {
  const limits = replyRecord(value);
  return {
    memory_bytes: replyNumber(limits.memory_bytes, 16 * 1024 ** 2, 2 ** 50),
    cpu_millis: replyNumber(limits.cpu_millis, 10, 1_024_000),
    pids: replyNumber(limits.pids, 16, 1_000_000),
  };
}
export function replyBudget(value: unknown): ManagedNode["budget"] {
  const budget = replyRecord(value),
    total = replyLimits(budget.total),
    reserved = replyLimits(budget.reserved);
  if ((["memory_bytes", "cpu_millis", "pids"] as const).some((key) => reserved[key] >= total[key]))
    throw Error("NODE_RESPONSE_INVALID");
  return { total, reserved };
}
