<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue"
import { InputNumber } from "ant-design-vue"
import { useI18n } from "vue-i18n"
import {
  controlPanelApi,
  type BrowserTabPolicy,
} from "@/shared/api/control-panel"
import Button from "@/shared/ui/Button.vue"
import Switch from "@/shared/ui/Switch.vue"

const props = defineProps<{ policy?: BrowserTabPolicy }>()
const emit = defineEmits<{ "policy-applied": [policy: BrowserTabPolicy] }>()
const { t } = useI18n()
const defaults: BrowserTabPolicy = {
  max_tabs: 20,
  idle_close_enabled: true,
  idle_timeout_seconds: 300,
}
const baseline = ref<BrowserTabPolicy>({ ...defaults })
const form = reactive<BrowserTabPolicy>({ ...defaults })
const loaded = ref(false)
const saving = ref(false)
const controlAction = ref<"" | "stop" | "restart">("")
const error = ref("")
const notice = ref("")
const dirty = computed(() =>
  Object.keys(defaults).some(
    (key) =>
      form[key as keyof BrowserTabPolicy] !==
      baseline.value[key as keyof BrowserTabPolicy],
  ),
)
function accept(policy: BrowserTabPolicy): void {
  const edited = dirty.value
  baseline.value = { ...policy }
  if (!edited) Object.assign(form, policy)
  loaded.value = true
}
watch(
  () => props.policy,
  (policy) => {
    if (policy) accept(policy)
  },
  { immediate: true },
)
async function loadPolicy(): Promise<void> {
  if (props.policy) return
  try {
    const state = await controlPanelApi.browserState()
    if (state.tab_policy) accept(state.tab_policy)
    else error.value = t("browser.tabPolicyUnavailable")
  } catch (caught) {
    error.value =
      caught instanceof Error ? caught.message : t("browser.connectionFailed")
  }
}
async function applyPolicy(): Promise<void> {
  if (!loaded.value || saving.value || !dirty.value) return
  saving.value = true
  error.value = ""
  notice.value = ""
  try {
    const result = await controlPanelApi.setBrowserTabPolicy({ ...form })
    const policy = result.tab_policy
    if (!policy) {
      error.value = t("browser.tabPolicyUnavailable")
      return
    }
    baseline.value = { ...policy }
    Object.assign(form, policy)
    emit("policy-applied", policy)
    notice.value = t("browser.tabPolicySaved")
  } catch (caught) {
    error.value =
      caught instanceof Error ? caught.message : t("browser.connectionFailed")
  } finally {
    saving.value = false
  }
}
function updateLimit(value: unknown): void {
  form.max_tabs =
    typeof value === "number" && Number.isFinite(value)
      ? Math.min(100, Math.max(1, Math.floor(value)))
      : defaults.max_tabs
}
function updateIdleTimeout(value: unknown): void {
  form.idle_timeout_seconds =
    typeof value === "number" && Number.isFinite(value)
      ? Math.min(86400, Math.max(30, Math.floor(value)))
      : defaults.idle_timeout_seconds
}
async function control(action: "stop" | "restart"): Promise<void> {
  if (controlAction.value) return
  controlAction.value = action
  error.value = ""
  notice.value = ""
  try {
    if (action === "stop") await controlPanelApi.browserHardStop()
    else await controlPanelApi.browserRestart()
    notice.value = t(
      action === "stop" ? "browser.stopped" : "browser.restarted",
    )
  } catch (caught) {
    error.value =
      caught instanceof Error ? caught.message : t("browser.connectionFailed")
  } finally {
    controlAction.value = ""
  }
}
onMounted(() => {
  void loadPolicy()
})
</script>

<template>
  <div class="space-y-3 border-t border-border pt-3">
    <h3 class="px-2 text-sm font-semibold">{{ t("browser.tabPolicy") }}</h3>
    <label class="flex items-center justify-between gap-3 px-2 text-sm">
      <span>{{ t("browser.maxTabs") }}</span>
      <InputNumber
        :value="form.max_tabs"
        :min="1"
        :max="100"
        :precision="0"
        :disabled="saving"
        class="w-28"
        size="middle"
        @update:value="updateLimit"
      />
    </label>
    <label class="flex items-center justify-between gap-3 px-2 text-sm">
      <span>{{ t("browser.idleCloseEnabled") }}</span>
      <Switch v-model="form.idle_close_enabled" :disabled="saving" />
    </label>
    <label
      v-if="form.idle_close_enabled"
      class="flex items-center justify-between gap-3 px-2 text-sm"
    >
      <span>{{ t("browser.idleCloseTimeout") }}</span>
      <InputNumber
        :value="form.idle_timeout_seconds"
        :min="30"
        :max="86400"
        :precision="0"
        :disabled="saving"
        class="w-28"
        size="middle"
        @update:value="updateIdleTimeout"
      />
    </label>
    <p class="px-2 text-[11px] text-muted-foreground">
      {{ t("browser.idleCloseHint") }}
    </p>
    <Button
      class="ml-2"
      variant="outline"
      size="default"
      :disabled="saving || !loaded || !dirty"
      @click="applyPolicy"
      >{{ t("browser.applyTabPolicy") }}</Button
    >
    <div class="flex flex-wrap gap-2 border-t border-border px-2 pt-3">
      <Button
        variant="outline"
        size="default"
        :disabled="Boolean(controlAction)"
        @click="control('stop')"
        >{{ t("services.stopBrowser") }}</Button
      >
      <Button
        variant="outline"
        size="default"
        :disabled="Boolean(controlAction)"
        @click="control('restart')"
        >{{ t("services.restartBrowser") }}</Button
      >
    </div>
    <p v-if="error" role="alert" class="px-2 text-sm text-destructive">
      {{ error }}
    </p>
    <p v-if="notice" role="status" class="px-2 text-sm text-muted-foreground">
      {{ notice }}
    </p>
  </div>
</template>
