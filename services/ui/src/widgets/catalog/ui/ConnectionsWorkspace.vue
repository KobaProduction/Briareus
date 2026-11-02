<script setup lang="ts">
import { computed, ref, watch } from "vue"
import { Plus, Trash2, PlugZap, Pencil } from "lucide-vue-next"
import type { VerifiedPlatformContext } from "@/entities/workspace"
import { connectionProviders, useConnections, BaseConnectionForm, type ConnectionProvider } from "@/features/catalog"
import { Button } from "@/shared/ui/button"
import ConfirmationDialog from "@/shared/ui/ConfirmationDialog.vue"
import { Badge } from "@/shared/ui/badge"
import { Tabs, TabsList, TabsTrigger } from "@/shared/ui/tabs"
import { Table, TableHeader, TableHead, TableRow, TableBody, TableCell } from "@/shared/ui/table"

const props = defineProps<{ context: VerifiedPlatformContext; selectedProjectId: string | null; embedded?: boolean; initialProvider?: ConnectionProvider }>()
defineEmits<{ selectProject: [id: string] }>()
const { live, ready, rows, busy, message, schemaReady, checks, editing, deleting, editingRow,
  deleteTarget, canEdit, open, submit, saved, check, remove } = useConnections({
  context: () => props.context, project: () => props.selectedProjectId,
})
const section = ref(props.initialProvider && ["signoz", "coolify"].includes(props.initialProvider) ? "infrastructure" : "vcs")
const selectedProvider = ref<ConnectionProvider>(props.initialProvider ?? "github")
const providers = computed<ConnectionProvider[]>(() => section.value === "vcs" ? ["github", "gitlab"] : ["signoz", "coolify"])
const displayed = computed(() => rows.value.filter(row => row.provider === selectedProvider.value))
watch(section, value => {
  const allowed: ConnectionProvider[] = value === "vcs" ? ["github", "gitlab"] : ["signoz", "coolify"]
  if (!allowed.includes(selectedProvider.value)) selectedProvider.value = value === "vcs" ? "github" : "signoz"
})
watch(() => props.initialProvider, value => {
  if (!value) return
  section.value = ["signoz", "coolify"].includes(value) ? "infrastructure" : "vcs"
  selectedProvider.value = value
})
const authLabels: Record<string, string> = { github_token: "GitHub token", github_app: "GitHub App", private_token: "Private token",
  bearer: "Bearer token", job_token: "Job token", signoz_api_key: "API key", coolify_api_token: "API token" }
const authLabel = (value: string): string => authLabels[value] ?? value
</script>

<template>
  <div class="space-y-5">
    <div v-if="!embedded" class="flex flex-wrap items-start justify-between gap-3">
      <div><h2 class="text-2xl font-semibold tracking-tight">Подключения</h2><p class="mt-1 text-sm text-muted-foreground">Учётные записи сервисов выбранного проекта</p></div>

    </div>
    <Tabs v-model="section"><TabsList><TabsTrigger value="vcs">Системы контроля версий</TabsTrigger><TabsTrigger value="infrastructure">Инфраструктура</TabsTrigger></TabsList></Tabs>
    <Tabs v-model="selectedProvider"><TabsList><TabsTrigger v-for="provider in providers" :key="provider" :value="provider">{{connectionProviders[provider].title}}</TabsTrigger></TabsList></Tabs>
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div><h3 class="text-xl font-semibold tracking-tight">{{connectionProviders[selectedProvider].title}}</h3><p class="mt-1 text-sm text-muted-foreground">{{connectionProviders[selectedProvider].description}}</p></div>
      <div class="flex items-center gap-2">
        <Button size="sm" :disabled="busy||!ready||!schemaReady||!canEdit(selectedProvider)" @click="open(selectedProvider)"><Plus class="mr-2 size-4"/>Добавить аккаунт</Button>
      </div>
    </div>
    <p v-if="context.user.role!=='operator'" class="rounded-lg border p-4 text-sm text-muted-foreground">Подключениями управляет оператор проекта.</p>
    <p v-if="message&&!editing" role="status" class="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm">{{message}}</p>
    <div class="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader><TableRow><TableHead>Название</TableHead><TableHead>Авторизация</TableHead><TableHead>Адрес сервиса</TableHead><TableHead class="text-right">Действия</TableHead></TableRow></TableHeader>
        <TableBody v-if="live">
          <TableRow v-for="row in displayed" :key="row.id">
            <TableCell class="font-medium">{{row.name}}<Badge v-if="checks[row.id]" variant="outline" class="ml-2">{{checks[row.id]}}</Badge></TableCell>
            <TableCell class="text-xs">{{authLabel(row.auth_type)}}</TableCell><TableCell class="text-xs text-muted-foreground">{{row.base_url}}</TableCell>
            <TableCell><div class="flex justify-end gap-1"><Button size="icon" variant="ghost" class="size-8" :disabled="busy||!ready" :aria-label="`Проверить ${row.name}`" @click="check(row)"><PlugZap class="size-4"/></Button><Button size="icon" variant="ghost" class="size-8" :disabled="busy||!ready||!canEdit(row.provider)" :aria-label="`Изменить ${row.name}`" @click="open(row.provider,row)"><Pencil class="size-4"/></Button><Button size="icon" variant="ghost" class="size-8" :disabled="busy||!ready" :aria-label="`Удалить ${row.name}`" @click="deleting=row.id"><Trash2 class="size-4"/></Button></div>
            </TableCell>
          </TableRow>
          <TableRow v-if="!displayed.length"><TableCell :colspan="4" class="h-28 text-center text-muted-foreground">{{busy?'Загружаем аккаунты…':'Аккаунты ещё не подключены'}}</TableCell></TableRow>
        </TableBody>
      </Table>
    </div>
    <ConfirmationDialog :open="!!deleteTarget" title="Удалить подключение?" :description="`Подключение ${deleteTarget?.name||''} будет удалено из проекта.`" confirm-label="Удалить" :busy="busy" @update:open="value=>{if(!value)deleting=null}" @confirm="deleteTarget&&remove(deleteTarget)"/>
    <BaseConnectionForm v-if="editing&&ready&&canEdit(editing)" :key="editingRow?.id??editing" :provider="editing" :initial="editingRow?.configuration" :busy="busy" :message="message" :submit="submit" @close="editing=null" @saved="saved"/>
  </div>
</template>
