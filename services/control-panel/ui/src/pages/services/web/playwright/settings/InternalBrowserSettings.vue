<script setup lang="ts">
import { onMounted, ref } from "vue"
import { Select } from "ant-design-vue"
import { useI18n } from "vue-i18n"
import { controlPanelApi, type BrowserState } from "@/shared/api/control-panel"
import Button from "@/shared/ui/Button.vue"
const { t } = useI18n()
const state = ref<BrowserState | null>(null)
const busy = ref(false),
  error = ref("")
const themes = [
  { value: "system", label: t("common.system") },
  { value: "dark", label: t("common.dark") },
  { value: "light", label: t("common.light") },
]
async function load(): Promise<void> {
  try {
    state.value = await controlPanelApi.browserState()
  } catch (caught) {
    error.value =
      caught instanceof Error ? caught.message : t("app.unavailable")
  }
}
async function theme(value: unknown): Promise<void> {
  if (value !== "dark" && value !== "light" && value !== "system") return
  busy.value = true
  try {
    state.value = await controlPanelApi.setBrowserTheme(value)
  } catch (caught) {
    error.value =
      caught instanceof Error ? caught.message : t("app.unavailable")
  } finally {
    busy.value = false
  }
}
async function control(action: "stop" | "restart"): Promise<void> {
  busy.value = true
  error.value = ""
  try {
    if (action === "stop") await controlPanelApi.browserHardStop()
    else await controlPanelApi.browserRestart()
    await load()
  } catch (caught) {
    error.value =
      caught instanceof Error ? caught.message : t("app.unavailable")
  } finally {
    busy.value = false
  }
}
onMounted(() => {
  void load()
})
</script>
<template>
  <section class="settings-card">
    <h2>Chromium</h2>
    <p v-if="error" role="alert" class="text-sm text-destructive">
      {{ error }}
    </p>
    <label class="setting-row"
      ><span
        ><b>{{ t("settings.browserTheme") }}</b
        ><small>{{ t("settings.browserThemeHint") }}</small></span
      ><Select
        :value="state?.color_scheme || 'system'"
        :options="themes"
        class="w-44"
        :disabled="busy"
        @change="theme"
    /></label>
    <div class="setting-row">
      <span
        ><b>{{ t("settings.browserViewport") }}</b
        ><small>{{ t("settings.browserViewportHint") }}</small></span
      ><span class="font-mono text-xs"
        >{{ state?.viewport?.width ?? 1280 }} ×
        {{ state?.viewport?.height ?? 720 }}</span
      >
    </div>
    <div class="flex gap-2">
      <Button
        variant="outline"
        size="sm"
        :disabled="busy"
        @click="control('stop')"
        >{{ t("services.stopBrowser") }}</Button
      ><Button
        variant="outline"
        size="sm"
        :disabled="busy"
        @click="control('restart')"
        >{{ t("services.restartBrowser") }}</Button
      >
    </div>
  </section>
</template>
