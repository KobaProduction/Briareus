import { defineStore, type Pinia } from "pinia"
import type { StateStore } from "oidc-client-ts"
import { panelPinia } from "../state/pinia"
import { browserPersistence, withBrowserLock } from "../state/persistence"

export const IDENTITY_STORAGE_KEY = "briareus:identity:v1"
const TRANSACTIONS_STORAGE_KEY = "briareus:oidc-transactions:v1"
interface Entry { key: string; value: string }

function deserialize(value: string): { entries: Entry[] } {
  try {
    const parsed: unknown = JSON.parse(value)
    if (!parsed || typeof parsed !== "object" || !("entries" in parsed) || !Array.isArray(parsed.entries)) return { entries: [] }
    return { entries: parsed.entries.filter((entry: unknown): entry is Entry => Boolean(
      entry && typeof entry === "object" && "key" in entry && typeof entry.key === "string"
      && "value" in entry && typeof entry.value === "string",
    )) }
  } catch {
    return { entries: [] }
  }
}

function entriesStore(id: string, key: string) {
  return defineStore(id, {
    state: () => ({ entries: [] as Entry[] }),
    persist: {
      key,
      storage: { getItem: key => browserPersistence.getItem(key) ?? '{"entries":[]}', setItem: browserPersistence.setItem },
      pick: ["entries"], serializer: { serialize: JSON.stringify, deserialize },
    },
  })
}

const useIdentityStore = entriesStore("oidc-identity", IDENTITY_STORAGE_KEY)
const useTransactionsStore = entriesStore("oidc-transactions", TRANSACTIONS_STORAGE_KEY)

function adapter(store: ReturnType<typeof useIdentityStore>): StateStore {
  const hydrate = () => store.$hydrate()
  return {
    async get(key) {
      return withBrowserLock(`storage:${store.$id}`, () => { hydrate(); return store.entries.find(entry => entry.key === key)?.value ?? null })
    },
    async getAllKeys() {
      return withBrowserLock(`storage:${store.$id}`, () => { hydrate(); return store.entries.map(entry => entry.key) })
    },
    async set(key, value) {
      await withBrowserLock(`storage:${store.$id}`, () => {
        hydrate()
        store.$patch({ entries: [...store.entries.filter(entry => entry.key !== key), { key, value }] })
      })
    },
    async remove(key) {
      return withBrowserLock(`storage:${store.$id}`, () => {
        hydrate()
        const value = store.entries.find(entry => entry.key === key)?.value ?? null
        store.$patch({ entries: store.entries.filter(entry => entry.key !== key) })
        return value
      })
    },
  }
}

export function identityStorage(pinia: Pinia = panelPinia): { users: StateStore; transactions: StateStore } {
  return { users: adapter(useIdentityStore(pinia)), transactions: adapter(useTransactionsStore(pinia)) }
}
