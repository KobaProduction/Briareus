<script setup lang="ts">
import { computed } from "vue"
import { defineStore } from "pinia"
import { useI18n } from "vue-i18n"
import { panelPinia } from "@/shared/state/pinia"
import { browserPersistence } from "@/shared/state/persistence"
import SectionTabs from "@/shared/ui/SectionTabs.vue"
import BrowserOperator from "./BrowserOperator.vue"
import InternalBrowserSettings from "./settings/InternalBrowserSettings.vue"
import ExternalBrowserSettings from "./settings/ExternalBrowserSettings.vue"
const { t } = useI18n()
const useMode = defineStore("playwright-ui", {
  state: () => ({ mode: "internal" }),
  persist: {
    key: "briareus:playwright-ui:v1",
    storage: browserPersistence,
    pick: ["mode"],
  },
})
const mode = useMode(panelPinia)
const modes = computed(() => [
  { id: "internal", label: t("services.internalBrowser") },
  { id: "external", label: t("settings.externalBrowser") },
])
function select(value: string): void {
  if (value === "internal" || value === "external") mode.mode = value
}
</script>
<template>
  <div class="space-y-5">
    <SectionTabs
      :model-value="mode.mode"
      :items="modes"
      @update:model-value="select"
    /><template v-if="mode.mode !== 'external'"
      ><BrowserOperator />
      <details class="rounded-xl border border-border bg-card p-4">
        <summary class="cursor-pointer text-sm font-medium">
          {{ t("settings.browser") }}
        </summary>
        <InternalBrowserSettings class="mt-4" /></details></template
    ><ExternalBrowserSettings v-else />
  </div>
</template>
