<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { InputNumber, Switch } from "ant-design-vue"
import { Save, Trash2 } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import { controlPanelApi, type SettingsState } from "@/shared/api/control-panel"
import { ControlPanelApiError } from "@/shared/api/error"
import { eventBus } from "@/shared/events/bus"
import { notifications } from "@/shared/notifications/bus"
import {
  IncompleteSettingsSnapshotError,
  settingsUpdatePayload,
} from "@/shared/settings/payload"
import { settingsStore } from "@/shared/settings/store"
import { useServiceCatalog } from "@/shared/services/store"
import InterfaceSettingsPanel from "./interface/InterfaceSettingsPanel.vue"
import Button from "@/shared/ui/Button.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"
import RefreshAction from "@/shared/ui/RefreshAction.vue"
import SectionTabs from "@/shared/ui/SectionTabs.vue"
const { t } = useI18n()
const catalog = useServiceCatalog()
const section = ref("interface"),
  loading = ref(false),
  saving = ref(false),
  error = ref("")
const state = ref<SettingsState | null>(null)
const form = reactive({
  logging_enabled: true,
  logging_capture_payloads: true,
  logging_retention_days: 30,
  logging_max_records: 10000,
  maintenance_interval_minutes: 60,
  mcp_call_timeout_seconds: 5,
})
const sections = computed(() => [
  {
    id: "interface",
    label: t("settings.interface"),
    description: t("settings.interfaceHint"),
  },
  {
    id: "realtime",
    label: t("settings.realtime"),
    description: t("settings.realtimeHint"),
  },
  {
    id: "logging",
    label: t("settings.logging"),
    description: t("settings.loggingHint"),
  },
  ...(catalog.connectedCount
    ? [
        {
          id: "mcp",
          label: t("settings.mcp"),
          description: t("settings.mcpHint"),
        },
      ]
    : []),
])
const pageSynced = computed(
  () =>
    settingsStore.state.synced &&
    state.value?.revision === settingsStore.state.value?.revision,
)
const liveTransport = computed(
  () => eventBus.state.enabled && eventBus.state.status === "connected",
)
function snapshot(value: SettingsState) {
  return {
    ...value.management,
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
  const child = location.hash.split("/")[1] ?? "interface"
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
  const result = await controlPanelApi.cleanupLogs()
  notifications.success(t("notifications.deleted"), String(result.removed))
}
watch(
  () => settingsStore.state.value,
  (value) => {
    if (value && (!state.value || !dirty.value)) apply(value)
  },
)
watch(() => catalog.connectedCount, readHash)
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
        v-if="section === 'logging' || section === 'mcp'"
        size="sm"
        :disabled="saving || loading || !state || !dirty"
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
    <section v-else-if="section === 'realtime'" class="settings-card max-w-3xl">
      <h2>{{ t("settings.realtime") }}</h2>
      <div class="setting-row">
        <span
          ><b>{{ t("settings.eventBus") }}</b
          ><small>{{ t("settings.eventBusHint") }}</small></span
        ><span class="text-xs">{{
          t(liveTransport ? "common.connected" : "common.disconnected")
        }}</span>
      </div>
    </section>
    <section v-else-if="section === 'logging'" class="settings-card max-w-3xl">
      <h2>{{ t("settings.logging") }}</h2>
      <label class="setting-row"
        ><span
          ><b>{{ t("settings.loggingEnabled") }}</b
          ><small>{{ t("settings.loggingEnabledHint") }}</small></span
        ><Switch v-model:checked="form.logging_enabled" /></label
      ><label class="setting-row"
        ><span
          ><b>{{ t("settings.capturePayloads") }}</b
          ><small>{{ t("settings.capturePayloadsHint") }}</small></span
        ><Switch v-model:checked="form.logging_capture_payloads" /></label
      ><label class="setting-row"
        ><span
          ><b>{{ t("settings.retentionDays") }}</b></span
        ><InputNumber
          v-model:value="form.logging_retention_days"
          :min="1"
          :max="3650" /></label
      ><label class="setting-row"
        ><span
          ><b>{{ t("settings.maxRecords") }}</b></span
        ><InputNumber
          v-model:value="form.logging_max_records"
          :min="100"
          :max="1000000" /></label
      ><label class="setting-row"
        ><span
          ><b>{{ t("settings.cleanupInterval") }}</b></span
        ><InputNumber
          v-model:value="form.maintenance_interval_minutes"
          :min="1"
          :max="1440" /></label
      ><Button variant="outline" size="sm" @click="cleanup"
        ><Trash2 class="mr-2 size-4" />{{
          t("settings.applyRetention")
        }}</Button
      >
    </section>
    <section v-else-if="section === 'mcp'" class="settings-card max-w-3xl">
      <h2>{{ t("settings.mcp") }}</h2>
      <label class="setting-row"
        ><span
          ><b>{{ t("settings.callTimeout") }}</b
          ><small>{{ t("settings.callTimeoutHint") }}</small></span
        ><InputNumber
          v-model:value="form.mcp_call_timeout_seconds"
          :min="1"
          :max="300"
      /></label>
    </section>
  </div>
</template>
