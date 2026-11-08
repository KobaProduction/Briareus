import { defineStore } from "pinia"
import {
  controlPanelApi,
  type ControlPanelBootstrap,
} from "../api/control-panel"
import { panelPinia } from "../state/pinia"
import { browserPersistence } from "../state/persistence"
import type { McpServiceDescriptor } from "./types"
import { groupedServices } from "./catalog"

const useCatalog = defineStore("mcp-service-catalog", {
  state: () => ({
    services: [] as McpServiceDescriptor[],
    checkedAt: "",
    showUnavailable: false,
    loading: false,
    error: false,
  }),
  getters: {
    groups: (state) => groupedServices(state.services, state.showUnavailable),
    connectedCount: (state) =>
      state.services.filter((service) => service.connected).length,
  },
  actions: {
    connected(id: string): boolean {
      return this.services.some(
        (service) => service.id === id && service.connected,
      )
    },
    service(id: string): McpServiceDescriptor | undefined {
      return this.services.find((service) => service.id === id)
    },
    accept(value: ControlPanelBootstrap): void {
      this.services = Array.isArray(value.services) ? value.services : []
      this.checkedAt = value.checked_at ?? ""
      this.error = false
    },
    clear(): void {
      this.services = []
      this.checkedAt = ""
      this.error = false
    },
    async refresh(): Promise<void> {
      if (this.loading) return
      this.loading = true
      try {
        this.accept(await controlPanelApi.bootstrap({ notifyErrors: false }))
      } catch {
        this.error = true
      } finally {
        this.loading = false
      }
    },
  },
  persist: {
    key: "briareus:service-catalog-ui:v1",
    storage: browserPersistence,
    pick: ["showUnavailable"],
  },
})
export function useServiceCatalog() {
  return useCatalog(panelPinia)
}
