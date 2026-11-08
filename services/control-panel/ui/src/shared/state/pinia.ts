import { createPinia } from "pinia"
import persistedState from "pinia-plugin-persistedstate"

export function createPanelPinia() {
  return createPinia().use(persistedState)
}

export const panelPinia = createPanelPinia()
