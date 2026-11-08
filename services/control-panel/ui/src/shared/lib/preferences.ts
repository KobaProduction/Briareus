import { watch } from "vue"
import { defineStore, storeToRefs } from "pinia"
import { browserLocale } from "./locale"
import { panelPinia } from "../state/pinia"
import { browserPersistence } from "../state/persistence"

export type ThemePreference = "dark" | "light" | "system"
export type DensityPreference = "comfortable" | "compact"
export type LocalePreference = "en" | "ru"
const STORAGE_KEY = "briareus:ui:v1"
type Preferences = { theme: ThemePreference; sidebarCollapsed: boolean; density: DensityPreference; locale: LocalePreference; telemetryEnabled: boolean }

function defaults(): Preferences {
  return { theme: "system", sidebarCollapsed: false, density: "compact", locale: browserLocale(), telemetryEnabled: true }
}

function preferences(value: unknown, legacy = false): Preferences {
  const result = defaults()
  if (!value || typeof value !== "object") return result
  if ("theme" in value && (value.theme === "dark" || value.theme === "light" || value.theme === "system")) result.theme = value.theme
  if ("sidebarCollapsed" in value && typeof value.sidebarCollapsed === "boolean") result.sidebarCollapsed = value.sidebarCollapsed
  if (!legacy && "density" in value && (value.density === "compact" || value.density === "comfortable")) result.density = value.density
  if ("locale" in value && (value.locale === "en" || value.locale === "ru")) result.locale = value.locale
  if ("telemetryEnabled" in value && typeof value.telemetryEnabled === "boolean") result.telemetryEnabled = value.telemetryEnabled
  return result
}

const usePreferencesStore = defineStore("ui-preferences", {
  state: defaults,
  persist: {
    key: STORAGE_KEY, storage: browserPersistence,
    pick: ["theme", "sidebarCollapsed", "density", "locale", "telemetryEnabled"],
    serializer: { serialize: JSON.stringify, deserialize: value => preferences(JSON.parse(value) as unknown) },
  },
})
const store = usePreferencesStore(panelPinia)
try {
  if (!browserPersistence.getItem(STORAGE_KEY)) {
    for (const key of ["mcp-bridge:ui:v2", "mcp-management:ui"]) {
      const previous = browserPersistence.getItem(key)
      if (previous) { store.$patch(preferences(JSON.parse(previous) as unknown, key === "mcp-management:ui")); break }
    }
  }
} catch { /* Ignore corrupt browser preferences. */ }

export const uiPreferences = storeToRefs(store)
export function useUiPreferences() { return uiPreferences }
watch(uiPreferences.theme, value => {
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches
  document.documentElement.classList.toggle("dark", value === "dark" || (value === "system" && dark))
}, { immediate: true })
watch(uiPreferences.density, value => { document.documentElement.dataset.density = value }, { immediate: true })
window.addEventListener("storage", event => {
  if (event.key === STORAGE_KEY) {
    if (event.newValue) store.$hydrate()
    else store.$patch(defaults())
  }
})
