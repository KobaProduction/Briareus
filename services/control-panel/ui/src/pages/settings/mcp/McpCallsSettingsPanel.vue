<script setup lang="ts">
import { InputNumber, Switch } from "ant-design-vue"
import { Trash2 } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import Button from "@/shared/ui/Button.vue"
import type { McpCallsSettingsForm } from "./types"

const props = defineProps<{ form: McpCallsSettingsForm; disabled: boolean; cleanupDisabled: boolean }>()
const emit = defineEmits<{ cleanup: [] }>()
const { t } = useI18n()

function setTimeout(value: unknown): void {
  props.form.mcp_call_timeout_seconds =
    typeof value === "number" && Number.isFinite(value) ? Math.max(0, value) : 0
}
</script>

<template>
  <section class="settings-card max-w-3xl">
    <h2>{{ t("settings.mcp") }}</h2>
    <p class="text-sm text-muted-foreground">{{ t("settings.mcpHint") }}</p>
    <label class="setting-row">
      <span
        ><b>{{ t("settings.callTimeout") }}</b
        ><small>{{ t("settings.callTimeoutHint") }}</small></span
      >
      <InputNumber
        :value="form.mcp_call_timeout_seconds"
        :min="0"
        :max="300"
        :disabled="disabled"
        @update:value="setTimeout"
      />
    </label>
    <label class="setting-row">
      <span
        ><b>{{ t("settings.loggingEnabled") }}</b
        ><small>{{ t("settings.loggingEnabledHint") }}</small></span
      >
      <Switch v-model:checked="form.logging_enabled" :disabled="disabled" />
    </label>
    <label class="setting-row">
      <span
        ><b>{{ t("settings.capturePayloads") }}</b
        ><small>{{ t("settings.capturePayloadsHint") }}</small></span
      >
      <Switch
        v-model:checked="form.logging_capture_payloads"
        :disabled="disabled"
      />
    </label>
    <label class="setting-row">
      <span
        ><b>{{ t("settings.retentionDays") }}</b></span
      >
      <InputNumber
        v-model:value="form.logging_retention_days"
        :min="1"
        :max="3650"
        :disabled="disabled"
      />
    </label>
    <label class="setting-row">
      <span
        ><b>{{ t("settings.maxRecords") }}</b></span
      >
      <InputNumber
        v-model:value="form.logging_max_records"
        :min="100"
        :max="1000000"
        :disabled="disabled"
      />
    </label>
    <label class="setting-row">
      <span
        ><b>{{ t("settings.cleanupInterval") }}</b></span
      >
      <InputNumber
        v-model:value="form.maintenance_interval_minutes"
        :min="1"
        :max="1440"
        :disabled="disabled"
      />
    </label>
    <Button
      variant="outline"
      size="sm"
      :disabled="disabled || cleanupDisabled"
      @click="emit('cleanup')"
      ><Trash2 class="mr-2 size-4" />{{ t("settings.applyRetention") }}</Button
    >
    <p class="text-xs text-muted-foreground">{{ t("settings.cleanupHint") }}</p>
  </section>
</template>
