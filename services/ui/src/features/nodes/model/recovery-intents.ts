import { isUuid4 } from "@/shared/lib/uuid";

export interface RecoveryIntent {
  id: string;
  sequence: number;
}
export interface RecoveryIntentStorage {
  read(key: string): unknown;
  write(key: string, intent: RecoveryIntent): void;
  remove(key: string): void;
}
function savedRecoveryIntent(value: unknown): RecoveryIntent | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  return isUuid4(item.id) &&
    typeof item.sequence === "number" &&
    Number.isSafeInteger(item.sequence) &&
    item.sequence > 0
    ? { id: item.id, sequence: item.sequence }
    : null;
}
/** An uncertain recovery retains its original operation and expected sequence.
 * Browser persistence is optional; neither storage nor this intent is authority. */
export function createRecoveryIntents(storage: RecoveryIntentStorage, nextId: () => string) {
  const memory = new Map<string, RecoveryIntent>();
  function acquire(key: string, sequence: number): RecoveryIntent {
    const existing = memory.get(key) ?? savedRecoveryIntent(storage.read(key));
    if (existing) {
      memory.set(key, existing);
      return existing;
    }
    const intent = { id: nextId(), sequence };
    memory.set(key, intent);
    storage.write(key, intent);
    return intent;
  }
  function complete(key: string): void {
    memory.delete(key);
    storage.remove(key);
  }
  return { acquire, complete };
}
