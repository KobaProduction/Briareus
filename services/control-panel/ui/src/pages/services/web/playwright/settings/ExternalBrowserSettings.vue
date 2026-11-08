<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue"
import { InputNumber, Switch } from "ant-design-vue"
import { useI18n } from "vue-i18n"
import {
  controlPanelApi,
  type BrowserExternalStatus,
} from "@/shared/api/control-panel"
import { settingsStore } from "@/shared/settings/store"
import { settingsUpdatePayload } from "@/shared/settings/payload"
import Button from "@/shared/ui/Button.vue"
const { t } = useI18n()
const state = computed(() => settingsStore.state.value)
const browserExternalStatus = ref<BrowserExternalStatus | null>(null)
const browserExternalAction = ref(""),
  error = ref(""),
  saving = ref(false),
  dirty = ref(false)
const form = reactive({
  browser_external_enabled: false,
  browser_external_mcp_url: "",
  browser_call_timeout_seconds: 300,
  browser_auto_disconnect_enabled: false,
  browser_idle_timeout_seconds: 300,
  browser_profile_dir_name: "Default",
  browser_extension_token: "",
  browser_clear_extension_token: false,
})
let poll: ReturnType<typeof setTimeout> | null = null
const externalBrowserBusy = computed(
  () => browserExternalStatus.value?.connecting === true,
)
const browserExternalStatusLabel = computed(() => {
  const status = browserExternalStatus.value
  if (!status) return t("settings.externalBrowserUnknown")
  if (!status.enabled) return t("settings.externalBrowserDisabled")
  if (status.connection_state === "tab_list_responded")
    return t("settings.externalBrowserTabsVerified")
  if (status.connection_state === "tab_check_failed")
    return t("settings.externalBrowserTabsFailed")
  return t(
    (status.proxy_connected ?? status.connected)
      ? "settings.externalBrowserProxyOnly"
      : "settings.externalBrowserProxyNotConnected",
  )
})
const externalBrowserPhaseLabel = computed(() =>
  t(
    (
      {
        mcp_initialize: "settings.externalBrowserInitializing",
        tools_list: "settings.externalBrowserDiscovering",
        tabs_list: "settings.externalBrowserCheckingTabs",
      } as Record<string, string>
    )[browserExternalStatus.value?.phase ?? ""] ??
      "settings.externalBrowserPending",
  ),
)
function schedule(): void {
  if (poll) clearTimeout(poll)
  if (externalBrowserBusy.value)
    poll = setTimeout(() => {
      void loadBrowser()
    }, 3500)
}
async function loadBrowser(): Promise<void> {
  try {
    browserExternalStatus.value = await controlPanelApi.browserExternalStatus()
    schedule()
  } catch (caught) {
    error.value =
      caught instanceof Error ? caught.message : t("app.unavailable")
  }
}
async function load(): Promise<void> {
  try {
    const next = await settingsStore.ensure()
    Object.assign(form, {
      browser_external_enabled: next.browser.external_enabled,
      browser_external_mcp_url: next.browser.external_mcp_url,
      browser_call_timeout_seconds: next.browser.call_timeout_seconds,
      browser_auto_disconnect_enabled: next.browser.auto_disconnect_enabled,
      browser_idle_timeout_seconds: next.browser.idle_timeout_seconds,
      browser_profile_dir_name: next.browser.profile_dir_name,
      browser_extension_token: "",
      browser_clear_extension_token: false,
    })
    dirty.value = false
    await loadBrowser()
  } catch (caught) {
    error.value =
      caught instanceof Error ? caught.message : t("app.unavailable")
  }
}
async function save(): Promise<void> {
  if (!state.value) return
  saving.value = true
  error.value = ""
  try {
    settingsStore.accept(
      await controlPanelApi.updateSettings(
        settingsUpdatePayload(state.value, { ...form }),
      ),
    )
    form.browser_extension_token = ""
    form.browser_clear_extension_token = false
    dirty.value = false
  } catch (caught) {
    error.value =
      caught instanceof Error ? caught.message : t("app.unavailable")
  } finally {
    saving.value = false
  }
}
async function runExternalBrowserAction(
  action: "connect" | "disconnect" | "reset",
): Promise<void> {
  if (browserExternalAction.value || dirty.value) return
  browserExternalAction.value = action
  error.value = ""
  try {
    browserExternalStatus.value =
      action === "connect"
        ? await controlPanelApi.browserExternalConnect()
        : action === "disconnect"
          ? await controlPanelApi.browserExternalDisconnect()
          : await controlPanelApi.browserExternalReset()
    schedule()
  } catch (caught) {
    error.value =
      caught instanceof Error ? caught.message : t("app.unavailable")
  } finally {
    browserExternalAction.value = ""
  }
}
watch(
  form,
  () => {
    dirty.value = true
  },
  { deep: true, flush: "sync" },
)
onMounted(() => {
  void load()
})
onBeforeUnmount(() => {
  if (poll) clearTimeout(poll)
})
</script>
<template>
  <section
    class="settings-card max-w-3xl"
    @input="dirty = true"
    @change="dirty = true"
  >
    <div class="flex items-center justify-between">
      <h2>{{ t("settings.externalBrowser") }}</h2>
      <Button size="sm" :disabled="saving || !state || !dirty" @click="save">{{
        t("common.save")
      }}</Button>
    </div>
    <p v-if="error" role="alert" class="text-sm text-destructive">
      {{ error }}
    </p>
    <label class="setting-row">
      <span
        ><b>{{ t("settings.externalBrowserEnabled") }}</b
        ><small>{{ t("settings.externalBrowserEnabledHint") }}</small></span
      >
      <Switch v-model:checked="form.browser_external_enabled" />
    </label>
    <label class="setting-row items-start">
      <span
        ><b>{{ t("settings.externalBrowserUrl") }}</b
        ><small>{{ t("settings.externalBrowserUrlHint") }}</small></span
      >
      <input
        v-model="form.browser_external_mcp_url"
        class="field w-full max-w-sm font-mono text-xs"
        placeholder="http://192.168.1.11:8931/mcp"
      />
    </label>
    <label class="setting-row">
      <span
        ><b>{{ t("settings.externalBrowserCallTimeout") }}</b
        ><small>{{ t("settings.externalBrowserCallTimeoutHint") }}</small></span
      >
      <InputNumber
        v-model:value="form.browser_call_timeout_seconds"
        :min="1"
        :max="1800"
      />
    </label>
    <label class="setting-row">
      <span
        ><b>{{ t("settings.externalBrowserAutoDisconnect") }}</b
        ><small>{{
          t("settings.externalBrowserAutoDisconnectHint")
        }}</small></span
      >
      <Switch v-model:checked="form.browser_auto_disconnect_enabled" />
    </label>
    <label v-if="form.browser_auto_disconnect_enabled" class="setting-row">
      <span
        ><b>{{ t("settings.externalBrowserIdleTimeout") }}</b
        ><small>{{ t("settings.externalBrowserIdleTimeoutHint") }}</small></span
      >
      <InputNumber
        v-model:value="form.browser_idle_timeout_seconds"
        :min="30"
        :max="86400"
      />
    </label>
    <label class="setting-row items-start">
      <span
        ><b>{{ t("settings.externalBrowserProfile") }}</b
        ><small>{{ t("settings.externalBrowserProfileHint") }}</small></span
      >
      <input
        v-model="form.browser_profile_dir_name"
        class="field w-56 font-mono text-xs"
        placeholder="Default"
      />
    </label>
    <label class="setting-row items-start">
      <span
        ><b>{{ t("settings.externalBrowserToken") }}</b
        ><small>{{
          state?.browser.extension_token_configured
            ? t("settings.externalBrowserTokenConfigured")
            : t("settings.externalBrowserTokenHint")
        }}</small></span
      >
      <input
        v-model="form.browser_extension_token"
        class="field w-full max-w-sm font-mono text-xs"
        type="password"
        autocomplete="off"
        :placeholder="
          state?.browser.extension_token_configured ? '••••••••' : ''
        "
      />
    </label>
    <label v-if="state?.browser.extension_token_configured" class="setting-row">
      <span
        ><b>{{ t("settings.externalBrowserClearToken") }}</b
        ><small>{{ t("settings.externalBrowserClearTokenHint") }}</small></span
      >
      <Switch v-model:checked="form.browser_clear_extension_token" />
    </label>
    <div class="setting-row">
      <span
        ><b>{{ t("settings.externalBrowserStatus") }}</b
        ><small>{{
          browserExternalStatus?.endpoint_origin ||
          form.browser_external_mcp_url ||
          "—"
        }}</small></span
      >
      <span
        class="rounded-md bg-muted px-2 py-1 text-xs"
        :class="
          browserExternalStatus?.connection_state === 'tab_list_responded'
            ? 'text-emerald-600'
            : 'text-muted-foreground'
        "
      >
        {{ browserExternalStatusLabel }}
      </span>
    </div>
    <p class="text-xs text-muted-foreground">
      {{ t("settings.externalBrowserScope") }}
    </p>
    <p
      v-if="externalBrowserBusy"
      role="status"
      aria-live="polite"
      class="text-xs text-muted-foreground"
    >
      <b>{{ externalBrowserPhaseLabel }}</b> —
      {{ browserExternalStatus?.next_action }}
    </p>
    <div
      v-if="browserExternalStatus?.last_error"
      role="alert"
      class="rounded-md border border-border p-3 text-xs"
    >
      <p class="font-semibold">
        {{ browserExternalStatus.last_error.code }} ·
        {{ browserExternalStatus.last_error.stage }}
      </p>
      <p class="mt-1">{{ browserExternalStatus.last_error.message }}</p>
      <p class="mt-1">{{ browserExternalStatus.last_error.next_action }}</p>
    </div>
    <p
      v-else-if="
        browserExternalStatus?.connection_state !== 'tab_list_responded'
      "
      class="text-xs text-muted-foreground"
    >
      {{
        browserExternalStatus?.next_action ||
        t("settings.externalBrowserNoProbe")
      }}
    </p>
    <div class="flex flex-wrap gap-2 pt-3">
      <Button
        size="sm"
        :disabled="
          Boolean(browserExternalAction) ||
          externalBrowserBusy ||
          dirty ||
          !form.browser_external_enabled ||
          !form.browser_external_mcp_url.trim()
        "
        @click="runExternalBrowserAction('connect')"
        >{{ t("settings.externalBrowserConnect") }}</Button
      >
      <Button
        variant="outline"
        size="sm"
        :disabled="Boolean(browserExternalAction)"
        @click="loadBrowser"
        >{{ t("settings.externalBrowserRefresh") }}</Button
      >
      <Button
        variant="outline"
        size="sm"
        :disabled="Boolean(browserExternalAction)"
        @click="runExternalBrowserAction('disconnect')"
        >{{ t("settings.externalBrowserDisconnect") }}</Button
      >
      <Button
        variant="outline"
        size="sm"
        :disabled="
          Boolean(browserExternalAction) ||
          dirty ||
          !form.browser_external_enabled ||
          !form.browser_external_mcp_url.trim()
        "
        @click="runExternalBrowserAction('reset')"
        >{{ t("settings.externalBrowserReset") }}</Button
      >
    </div>
  </section>
</template>
