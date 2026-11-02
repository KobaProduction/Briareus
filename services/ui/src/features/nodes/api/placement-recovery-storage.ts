import type { RecoveryIntentStorage } from "../model/recovery-intents";
export const placementRecoveryStorage: RecoveryIntentStorage = {
  read(key) {
    try {
      return JSON.parse(sessionStorage.getItem(key) ?? "null") as unknown;
    } catch {
      return null;
    }
  },
  write(key, intent) {
    try {
      sessionStorage.setItem(key, JSON.stringify(intent));
    } catch {
      /* Optional browser persistence. */
    }
  },
  remove(key) {
    try {
      sessionStorage.removeItem(key);
    } catch {
      /* Optional browser persistence. */
    }
  },
};
