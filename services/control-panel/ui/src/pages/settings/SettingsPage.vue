<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { Save } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import { controlPanelApi, type SettingsState } from "@/shared/api/control-panel"
import { ControlPanelApiError } from "@/shared/api/error"
import { notifications } from "@/shared/notifications/bus"
import {
  IncompleteSettingsSnapshotError,
  settingsUpdatePayload,
} from "@/shared/settings/payload"
import { settingsStore } from "@/shared/settings/store"
import InterfaceSettingsPanel from "./interface/InterfaceSettingsPanel.vue"
import TelemetryPanel from "@/features/telemetry/TelemetryPanel.vue"
import McpCallsSettingsPanel from "./mcp/McpCallsSettingsPanel.vue"
import type { McpCallsSettingsForm } from "./mcp/types"
import Button from "@/shared/ui/Button.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"
import RefreshAction from "@/shared/ui/RefreshAction.vue"
import SectionTabs from "@/shared/ui/SectionTabs.vue"
const { t } = useI18n()
const section = ref("interface"),
  loading = ref(false),
  saving = ref(false),
  cleaning = ref(false),
  error = ref("")
const state = ref<SettingsState | null>(null)
const form = reactive<McpCallsSettingsForm>({
  logging_enabled: true,
  logging_capture_payloads: true,
  logging_retention_days: 30,
  logging_max_records: 10000,
  maintenance_interval_minutes: 60,
  mcp_call_timeout_seconds: 0,
})
const sections = computed(() => [
  {
    id: "interface",
    label: t("settings.interface"),
    description: t("settings.interfaceHint"),
  },
  {
    id: "telemetry",
    label: t("settings.telemetry"),
    description: t("settings.telemetryHint"),
  },
  { id: "mcp", label: t("settings.mcp"), description: t("settings.mcpHint") },
])
const pageSynced = computed(
  () =>
    settingsStore.state.synced &&
    state.value?.revision === settingsStore.state.value?.revision,
)
function snapshot(value: SettingsState): McpCallsSettingsForm {
  return {
    logging_enabled: value.management.logging_enabled,
    logging_capture_payloads: value.management.logging_capture_payloads,
    logging_retention_days: value.management.logging_retention_days,
    logging_max_records: value.management.logging_max_records,
    maintenance_interval_minutes: value.management.maintenance_interval_minutes,
    mcp_call_timeout_seconds: value.mcp.call_timeout_seconds,
  }
}
const dirty = computed(() =>
  state.value
    ? Object.entries(form).some(
        ([key, value]) =>
          snapshot(state.value!)[key as keyof ReturnType<typeof snapshot>] !==
          value,
      )
    : false,
)
function apply(value: SettingsState): void {
  state.value = value
  Object.assign(form, snapshot(value))
}
function readHash(): void {
  const route = location.hash.split("/")[1] ?? "interface"
  const child = route === "logging" ? "mcp" : route
  section.value = sections.value.some((item) => item.id === child)
    ? child
    : "interface"
}
function select(value: string): void {
  if (!sections.value.some((item) => item.id === value)) return
  section.value = value
  history.replaceState(null, "", `#settings/${value}`)
}
async function load(): Promise<void> {
  loading.value = true
  error.value = ""
  try {
    const next = await settingsStore.refresh()
    if (!dirty.value || !state.value) apply(next)
    else if (next.revision !== state.value.revision)
      error.value = t("settings.conflict")
  } catch (caught) {
    error.value =
      caught instanceof Error ? caught.message : t("app.unavailable")
  } finally {
    loading.value = false
  }
}
async function save(): Promise<void> {
  if (!state.value) return
  saving.value = true
  error.value = ""
  try {
    const saved = await controlPanelApi.updateSettings(
      settingsUpdatePayload(state.value, { ...form }),
    )
    settingsStore.accept(saved)
    apply(saved)
    notifications.success(t("notifications.saved"))
  } catch (caught) {
    error.value =
      caught instanceof IncompleteSettingsSnapshotError
        ? t("settings.reloadBeforeSave")
        : caught instanceof ControlPanelApiError && caught.status === 409
          ? t("settings.conflict")
          : caught instanceof Error
            ? caught.message
            : t("app.unavailable")
  } finally {
    saving.value = false
  }
}
async function cleanup(): Promise<void> {
  cleaning.value = true
  error.value = ""
  try {
    const result = await controlPanelApi.cleanupLogs()
    notifications.success(t("settings.cleanupDone", { count: result.removed }))
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : t("app.unavailable")
  } finally {
    cleaning.value = false
  }
}
watch(
  () => settingsStore.state.value,
  (value) => {
    if (value && (!state.value || !dirty.value)) apply(value)
  },
)
onMounted(() => {
  readHash()
  window.addEventListener("hashchange", readHash)
  if (settingsStore.state.value) apply(settingsStore.state.value)
  else
    void settingsStore
      .ensure()
      .then(apply)
      .catch((caught) => {
        error.value =
          caught instanceof Error ? caught.message : t("app.unavailable")
      })
})
onBeforeUnmount(() => window.removeEventListener("hashchange", readHash))
</script>
<template>
  <div class="space-y-5">
    <PageHeader
      :title="t('settings.title')"
      :description="t('settings.description')"
      ><RefreshAction
        :synced="pageSynced"
        :loading="loading || settingsStore.state.loading"
        @refresh="load"
      /><Button
        v-if="section === 'mcp'"
        size="sm"
        :disabled="saving || cleaning || loading || !state || !dirty"
        @click="save"
        ><Save class="mr-2 size-4" />{{ t("common.save") }}</Button
      ></PageHeader
    ><SectionTabs
      :model-value="section"
      :items="sections"
      @update:model-value="select"
    />
    <p
      v-if="error"
      role="alert"
      class="rounded-lg bg-destructive/10 p-3 text-sm text-destructive"
    >
      {{ error }}
    </p>
    <InterfaceSettingsPanel v-if="section === 'interface'" />
    <TelemetryPanel v-else-if="section === 'telemetry'" />
    <McpCallsSettingsPanel
      v-else-if="section === 'mcp'"
      :form="form"
      :disabled="saving || cleaning || loading || !state"
      :cleanup-disabled="dirty"
      @cleanup="cleanup"
    />
  </div>
</template>
