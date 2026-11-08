<script setup lang="ts">
import { computed, ref } from "vue"
import { Cable, Copy } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import { useServiceCatalog } from "@/shared/services/store"
import { serviceConnectionUrl } from "@/shared/services/catalog"
import type { McpServiceDescriptor } from "@/shared/services/types"
import type { DataTableColumn } from "@/shared/ui/table"
import { notifications } from "@/shared/notifications/bus"
import AppDialog from "@/shared/ui/AppDialog.vue"
import Button from "@/shared/ui/Button.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"
import RefreshAction from "@/shared/ui/RefreshAction.vue"
import Switch from "@/shared/ui/Switch.vue"
const { t, te } = useI18n()
const catalog = useServiceCatalog()
const selectedId = ref<string | null>(null)
const selected = computed(() => selectedId.value ? catalog.service(selectedId.value) : undefined)
const rows = computed(() => catalog.groups.flatMap((group) => group.services))
const columns = computed<DataTableColumn[]>(() => [
  { title: t("services.service"), dataIndex: "name", key: "name", width: 180 },
  { title: t("services.group"), dataIndex: "group", key: "group", width: 130 },
  { title: t("common.status"), dataIndex: "connected", key: "connected", width: 140 },
  { title: t("services.address"), dataIndex: "mcp_path", key: "address" },
  { title: "", key: "actions", width: 190 },
])
function groupLabel(id: string): string {
  return te(`services.groups.${id}`) ? t(`services.groups.${id}`) : id
}
function url(service: McpServiceDescriptor): string | null {
  return serviceConnectionUrl(service.mcp_path, location.origin)
}
async function copy(service: McpServiceDescriptor): Promise<void> {
  const address = url(service)
  if (!address) return
  try {
    await navigator.clipboard.writeText(address)
    notifications.success(t("services.addressCopied"))
  } catch {
    notifications.error(t("services.copyFailed"))
  }
}
</script>
<template>
  <div class="space-y-5">
    <PageHeader :title="t('services.connections')" :description="t('services.connectionDescription')">
      <RefreshAction :synced="!catalog.error && !!catalog.checkedAt" :loading="catalog.loading" @refresh="catalog.refresh" />
    </PageHeader>
    <section aria-labelledby="mcp-services-heading" class="overflow-hidden rounded-xl border border-border bg-card">
      <div class="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <h2 id="mcp-services-heading" class="text-sm font-semibold">{{ t("services.title") }}</h2>
        <label class="inline-flex cursor-pointer items-center gap-2 text-sm text-muted-foreground">
          <Switch v-model="catalog.showUnavailable" />{{ t("services.showUnavailable") }}
        </label>
      </div>
      <p v-if="catalog.error" role="status" class="border-b border-border px-4 py-3 text-sm text-amber-700 dark:text-amber-300">{{ t("services.discoveryUnavailable") }}</p>
      <div class="h-[min(62vh,560px)] min-h-72 overflow-hidden">
        <DataTable :columns="columns" :data-source="rows" :loading="catalog.loading" row-key="id" :framed="false" fill-height class="h-full">
          <template #bodyCell="{column, record}">
            <span v-if="column.key === 'name'" class="font-medium">{{ record.name }}</span>
            <span v-else-if="column.key === 'group'" class="text-muted-foreground">{{ groupLabel(record.group) }}</span>
            <span v-else-if="column.key === 'connected'" class="inline-flex items-center gap-2 text-xs" :class="record.connected ? 'text-emerald-600 dark:text-emerald-400' : 'text-muted-foreground'">
              <span class="size-1.5 rounded-full" :class="record.connected ? 'bg-emerald-500' : 'bg-muted-foreground/50'" />
              {{ t(record.connected ? 'common.connected' : 'common.disconnected') }}
            </span>
            <code v-else-if="column.key === 'address'" class="block truncate text-xs text-muted-foreground" :title="url(record) ?? undefined">{{ url(record) ?? '—' }}</code>
            <div v-else-if="column.key === 'actions'" class="flex items-center justify-end gap-1">
              <Button variant="ghost" size="sm" :aria-label="t('services.copyAddress', {name: record.name})" :title="t('jsonView.copy')" :disabled="!record.connected || !url(record)" @click="copy(record)"><Copy class="size-3.5" /></Button>
              <Button variant="outline" size="sm" :disabled="!record.connected || !url(record)" @click="selectedId = record.id"><Cable class="mr-2 size-3.5" />{{ t("services.connect") }}</Button>
            </div>
          </template>
        </DataTable>
      </div>
    </section>
    <AppDialog :open="!!selected" :title="t('services.connectService', {name:selected?.name ?? ''})" @close="selectedId = null" :close-label="t('common.close')">
      <div v-if="selected" class="space-y-4">
        <p class="text-sm text-muted-foreground">{{ t("services.connectHint") }}</p>
        <label class="block space-y-2 text-sm"><span>{{ t("services.address") }}</span><input readonly :value="url(selected) ?? ''" class="field font-mono text-xs" @focus="($event.target as HTMLInputElement).select()" /></label>
        <Button :disabled="!selected.connected" @click="copy(selected)"><Copy class="mr-2 size-4" />{{ t("jsonView.copy") }}</Button>
      </div>
    </AppDialog>
  </div>
</template>
