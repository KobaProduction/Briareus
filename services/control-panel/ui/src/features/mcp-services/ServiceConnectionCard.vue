<script setup lang="ts">
import { computed, ref } from "vue"
import { useI18n } from "vue-i18n"
import { useServiceCatalog } from "@/shared/services/store"
import { serviceConnectionUrl } from "@/shared/services/catalog"
import Button from "@/shared/ui/Button.vue"
const props = defineProps<{ serviceId: string }>()
const { t } = useI18n()
const catalog = useServiceCatalog()
const copied = ref(false)
const service = computed(() => catalog.service(props.serviceId))
const url = computed(() =>
  service.value
    ? serviceConnectionUrl(service.value.mcp_path, location.origin)
    : null,
)
async function copy(): Promise<void> {
  if (!url.value || !service.value?.connected) return
  await navigator.clipboard.writeText(url.value)
  copied.value = true
}
</script>
<template>
  <section v-if="service" class="rounded-xl border border-border bg-card p-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <h2 class="font-semibold">{{ service.name }} MCP</h2>
      <span
        class="text-xs"
        :class="
          service.connected ? 'text-emerald-600' : 'text-muted-foreground'
        "
        >{{
          t(service.connected ? "common.connected" : "common.disconnected")
        }}</span
      >
    </div>
    <p class="mt-2 text-sm text-muted-foreground">
      {{ t("services.connectHint") }}
    </p>
    <div v-if="url" class="mt-3 flex flex-wrap items-center gap-3">
      <code class="break-all rounded-md bg-muted px-2 py-1 text-xs">{{
        url
      }}</code
      ><Button
        variant="outline"
        size="sm"
        :disabled="!service.connected"
        @click="copy"
        >{{ t(copied ? "jsonView.copied" : "jsonView.copy") }}</Button
      >
    </div>
  </section>
</template>
