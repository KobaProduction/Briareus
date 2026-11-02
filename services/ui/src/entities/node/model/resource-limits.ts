import type { ResourceLimits } from "./types";

export const MEBIBYTE = 1024 ** 2;
export const DEFAULT_NODE_LIMITS: Readonly<ResourceLimits> = {
  memory_bytes: 2048 * MEBIBYTE,
  cpu_millis: 2000,
  pids: 512,
};
export const NODE_RESERVED_LIMITS: Readonly<ResourceLimits> = {
  memory_bytes: 384 * MEBIBYTE,
  cpu_millis: 750,
  pids: 192,
};
export const MINIMUM_MODULE_LIMITS: Readonly<ResourceLimits> = {
  memory_bytes: 64 * MEBIBYTE,
  cpu_millis: 100,
  pids: 32,
};

/** Editable allocations use whole MiB, CPU millis and PID counts. */
export function resourceAllocationAllowed(
  limits: ResourceLimits,
  minimum: ResourceLimits,
  maximum: ResourceLimits,
): boolean {
  if (!Number.isInteger(limits.memory_bytes / MEBIBYTE)) return false;
  return (["memory_bytes", "cpu_millis", "pids"] as const).every(
    (key) =>
      Number.isInteger(limits[key]) && limits[key] >= minimum[key] && limits[key] <= maximum[key],
  );
}

/** The node's own reserve must remain available when execution budgets change. */
export function nodeBudgetAllowed(limits: ResourceLimits): boolean {
  return (
    Number.isInteger(limits.memory_bytes / MEBIBYTE) &&
    limits.memory_bytes >= 512 * MEBIBYTE &&
    Number.isInteger(limits.cpu_millis) &&
    limits.cpu_millis > NODE_RESERVED_LIMITS.cpu_millis &&
    Number.isInteger(limits.pids) &&
    limits.pids > NODE_RESERVED_LIMITS.pids
  );
}
