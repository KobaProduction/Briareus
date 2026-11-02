import {recordValue} from "./transport"
import { ref, watch } from "vue"
import {timeUpdateIntervalMs} from "./presentation-clock"

export type DensityPreference = "comfortable" | "compact"
export type LocalePreference = "en" | "ru"
/** Display preference ONLY. Never changes server TZ, audit timestamps or
 * authenticated Team/Project policies. */
export type DisplayTimeZone = "system" | "UTC"

const STORAGE_KEY = "briareus:ui:v1"
const sidebarCollapsed = ref(false)
const density = ref<DensityPreference>("compact")
const locale = ref<LocalePreference>("ru")
const displayTimeZone = ref<DisplayTimeZone>("system")
/** B16: diagnostics consent is SESSION/TAB-local. An earlier User cannot
 * authorize collection for another User via persisted browser preference. */
const diagnosticsConsent = ref(false)

function applyStored(value:unknown): void {
  const p=recordValue(value);if(!p)return;
  const interval=p.timeUpdateIntervalMs;
  if(typeof interval==="number"&&[1000,5000,15000,60000].includes(interval))timeUpdateIntervalMs.value=interval
  if (typeof p.sidebarCollapsed === "boolean") sidebarCollapsed.value = p.sidebarCollapsed
  if (p.density === "compact" || p.density === "comfortable") density.value = p.density
  if (p.locale === "en" || p.locale === "ru") locale.value = p.locale
  if (p.displayTimeZone === "UTC" || p.displayTimeZone === "system")displayTimeZone.value = p.displayTimeZone
}

function readPreferences(): void {
  try {
    const current = localStorage.getItem(STORAGE_KEY)
    if (current) {
      applyStored(JSON.parse(current))
      return
    }
  } catch {
    // Ignore corrupt browser-local preferences.
  }
}

function persist(): void {
  // Storage can be disabled or quota-limited; a display preference must not
  // break sign-in or crash the mounted Control Panel.
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      sidebarCollapsed: sidebarCollapsed.value,
      density: density.value,
      locale: locale.value,
      displayTimeZone: displayTimeZone.value,
      timeUpdateIntervalMs:timeUpdateIntervalMs.value,
    }))
  } catch { /* Keep the active tab preference in memory. */ }
}

function applyDensity(): void {
  document.documentElement.dataset.density = density.value
}

readPreferences()
watch([sidebarCollapsed, density, locale, displayTimeZone,timeUpdateIntervalMs], persist)
// Revoke the previous B14 persisted consent grant. A fresh page/tab/user
// always starts with diagnostics OFF; never read a previously stored opt-in.
try {localStorage.removeItem("briareus:diagnostics-consent:v1")}catch{/* no storage access */}
// One fixed Bridge palette. Old stored appearance choices are ignored.
document.documentElement.classList.add("dark")
delete document.documentElement.dataset.accent
watch(density, applyDensity, { immediate: true })

window.addEventListener("storage", (event) => {
  if (event.key !== STORAGE_KEY || !event.newValue) return
  try {
    applyStored(JSON.parse(event.newValue))
  } catch {
    // Ignore corrupt cross-tab preference events.
  }
})

export const uiPreferences = { sidebarCollapsed, density, locale, displayTimeZone, diagnosticsConsent,timeUpdateIntervalMs }
export function useUiPreferences() { return uiPreferences }
