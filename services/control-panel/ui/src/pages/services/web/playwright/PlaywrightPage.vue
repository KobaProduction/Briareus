<script setup lang="ts">
import { computed, ref } from "vue"
import { defineStore } from "pinia"
import { useI18n } from "vue-i18n"
import { panelPinia } from "@/shared/state/pinia"
import { browserPersistence } from "@/shared/state/persistence"
import { Settings } from "lucide-vue-next"
import Button from "@/shared/ui/Button.vue"
import AppDialog from "@/shared/ui/AppDialog.vue"
import SectionTabs from "@/shared/ui/SectionTabs.vue"
import BrowserOperator from "./BrowserOperator.vue"
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
const externalSettingsOpen = ref(false)
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
    />
    <BrowserOperator v-if="mode.mode !== 'external'" />
    <section v-else class="rounded-xl border border-border bg-card p-6">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div><h2 class="font-semibold">{{ t("settings.externalBrowser") }}</h2><p class="mt-2 max-w-xl text-sm text-muted-foreground">{{ t("settings.externalBrowserScope") }}</p></div>
        <Button variant="outline" @click="externalSettingsOpen = true"><Settings class="mr-2 size-4" />{{ t("browser.playwrightSettings") }}</Button>
      </div>
    </section>
    <AppDialog :open="externalSettingsOpen" :title="t('settings.externalBrowser')" :close-label="t('common.close')" width="880px" @close="externalSettingsOpen = false">
      <ExternalBrowserSettings v-if="externalSettingsOpen" />
      <template #footer><Button variant="outline" @click="externalSettingsOpen = false">{{ t("common.close") }}</Button></template>
    </AppDialog>
  </div>
</template>
