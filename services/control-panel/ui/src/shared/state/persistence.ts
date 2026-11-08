import type { StorageLike } from "pinia-plugin-persistedstate"

// Browser storage is accessed only by the Pinia persistence boundary.
export const browserPersistence: StorageLike = {
  getItem: key => window.localStorage.getItem(key),
  setItem: (key, value) => window.localStorage.setItem(key, value),
}

export async function withBrowserLock<T>(name: string, operation: () => Promise<T> | T): Promise<T> {
  if (typeof navigator !== "undefined" && navigator.locks) {
    return navigator.locks.request(`briareus:${name}`, operation)
  }
  return operation()
}
