<script setup lang="ts">
import { computed } from "vue"
import { Select } from "ant-design-vue"
import { useI18n } from "vue-i18n"
import { setLocale } from "@/shared/i18n"
import { uiPreferences } from "@/shared/lib/preferences"
import TelemetryPanel from "@/features/telemetry/TelemetryPanel.vue"
const { t } = useI18n()
const languages = [
  { label: "Русский", value: "ru" },
  { label: "English", value: "en" },
]
const themes = computed(() => [
  { label: t("common.system"), value: "system" },
  { label: t("common.dark"), value: "dark" },
  { label: t("common.light"), value: "light" },
])
const densities = computed(() => [
  { label: t("common.comfortable"), value: "comfortable" },
  { label: t("common.compact"), value: "compact" },
])
function locale(value: unknown): void {
  if (value === "en" || value === "ru") setLocale(value)
}
</script>
<template>
  <div class="space-y-6">
    <section class="settings-card max-w-3xl">
      <h2>{{ t("settings.interface") }}</h2>
      <label class="setting-row"
        ><span
          ><b>{{ t("settings.language") }}</b
          ><small>{{ t("settings.languageHint") }}</small></span
        ><Select
          :value="uiPreferences.locale.value"
          :options="languages"
          class="w-44"
          @change="locale" /></label
      ><label class="setting-row"
        ><span
          ><b>{{ t("settings.theme") }}</b
          ><small>{{ t("settings.themeHint") }}</small></span
        ><Select
          v-model:value="uiPreferences.theme.value"
          :options="themes"
          class="w-44" /></label
      ><label class="setting-row"
        ><span
          ><b>{{ t("settings.density") }}</b
          ><small>{{ t("settings.densityHint") }}</small></span
        ><Select
          v-model:value="uiPreferences.density.value"
          :options="densities"
          class="w-44"
      /></label>
    </section>
    <TelemetryPanel />
  </div>
</template>
