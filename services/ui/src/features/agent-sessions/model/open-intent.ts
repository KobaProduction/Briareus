import {
  type ElevationPolicy,
  NORMAL_SESSION_MAX_AGE_MS as MAX_AGE_MS,
} from "@/entities/agent-session";
import { type BoundedLifetime, boundedLifetime } from "@/shared/lib/lifetime";
import { isUuid4 } from "@/shared/lib/uuid";
export interface PreparedNormalSessionOpen {
  readonly project: string;
  readonly policy: ElevationPolicy;
  readonly label: string;
  readonly operation: string;
  readonly body: string;
}
export type SessionOpenPreparation =
  | { kind: "prepared"; command: PreparedNormalSessionOpen }
  | { kind: "invalid" | "unavailable"; code: string };
// Stop replay after the normal session's 24h lifetime, well before Access's
// seven-day idempotency retention. Never reuse an indefinitely old key after
// its owner may legitimately have removed the deduplication record.
const preparedCommands = new WeakMap<PreparedNormalSessionOpen, BoundedLifetime>();
export function prepareNormalSessionOpen(
  project: string,
  policy: ElevationPolicy,
  label: string,
): SessionOpenPreparation {
  if (
    !isUuid4(project) ||
    !["fixed", "requestable"].includes(policy) ||
    label.length > 128 ||
    label.trim() !== label ||
    [...label].some((c) => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127)
  )
    return { kind: "invalid", code: "AGENT_SESSION_INPUT_INVALID" };
  if (typeof crypto === "undefined" || typeof crypto.randomUUID !== "function")
    return { kind: "unavailable", code: "SECURE_CONTEXT_REQUIRED" };
  const command = Object.freeze({
    project,
    policy,
    label,
    operation: crypto.randomUUID(),
    body: JSON.stringify({
      project_uuid: project,
      elevation_policy: policy,
      label: label.length > 0 ? label : null,
    }),
  });
  preparedCommands.set(command, boundedLifetime(Date.now() + MAX_AGE_MS));
  return { kind: "prepared", command };
}
/** Caller revalidates current User/Project before every explicitly requested
 * execution, including a replay. No automatic retry or permission cache. */
export function normalSessionReplayRemaining(command: PreparedNormalSessionOpen): number {
  return preparedCommands.get(command)?.remainingMilliseconds() ?? 0;
}

export function knownPreparedOpen(command: PreparedNormalSessionOpen): boolean {
  return preparedCommands.has(command);
}
