<script setup lang="ts">
import { requestConfirmation } from "@/shared/ui/confirmation"
import { computed, onMounted, onBeforeUnmount, ref } from "vue"
import { InputNumber, Modal, Select, Tag } from "ant-design-vue"
import { RefreshCw, Save, Trash2 } from "lucide-vue-next"
import { useI18n } from "vue-i18n"
import {
  controlPanelApi,
  type SettingsState,
  type TerminalJobState,
  type TerminalState,
} from "@/shared/api/control-panel"
import { formatBytes, formatDate, textValue } from "@/shared/lib/format"
import { notifications } from "@/shared/notifications/bus"
import { settingsUpdatePayload } from "@/shared/settings/payload"
import { pageActivity } from "@/shared/lib/page-activity"
import Button from "@/shared/ui/Button.vue"
import DataTable from "@/shared/ui/DataTable.vue"
import LoadingSkeleton from "@/shared/ui/LoadingSkeleton.vue"
import PageHeader from "@/shared/ui/PageHeader.vue"
import StatCard from "@/shared/ui/StatCard.vue"

const { t } = useI18n()
const state = ref<TerminalState | null>(null),
  settings = ref<SettingsState | null>(null),
  loading = ref(false),
  error = ref(""),
  selected = ref<TerminalJobState | null>(null),
  maxProcesses = ref(16),
  jobFilter = ref("all"),
  maxExec = ref(21600),
  maxJob = ref(43200),
  savingPolicy = ref(false)
const policyDirty = computed(() => !!settings.value && (
  maxExec.value !== settings.value.terminal.max_exec_timeout_seconds ||
  maxJob.value !== settings.value.terminal.max_job_runtime_seconds ||
  maxProcesses.value !== (settings.value.terminal.max_concurrent_processes ?? 16)
))
const jobs = computed(() => state.value?.jobs ?? []),
  workspaces = computed(() => state.value?.workspaces ?? [])
const filteredJobs = computed(() => jobs.value.filter(job => jobFilter.value === "all" || (jobFilter.value === "active") === ["running", "cancelling"].includes(String(job.state))))
let poll: ReturnType<typeof setInterval> | undefined
const running = computed(
    () =>
      jobs.value.filter((item) =>
        ["running", "cancelling"].includes(String(item.state)),
      ).length,
  ),
  failed = computed(
    () =>
      jobs.value.filter((item) =>
        ["failed", "interrupted"].includes(String(item.state)),
      ).length,
  )
const workspaceColumns = [
  {
    title: t("terminal.workspace"),
    dataIndex: "workspace_id",
    key: "workspace_id",
  },
  {
    title: t("terminal.activeJobs"),
    dataIndex: "active_jobs",
    key: "active_jobs",
    width: 120,
  },
  { title: t("analysis.path"), dataIndex: "path", key: "path" },
  { title: t("common.actions"), key: "actions", width: 100 },
]
const jobColumns = [
  { title: t("terminal.job"), dataIndex: "job_id", key: "job_id", width: 150 },
  {
    title: t("terminal.workspace"),
    dataIndex: "workspace_id",
    key: "workspace_id",
    width: 150,
  },
  { title: t("terminal.state"), dataIndex: "state", key: "state", width: 110 },
  {
    title: t("terminal.duration"),
    dataIndex: "duration_seconds",
    key: "duration_seconds",
    width: 100,
  },
  { title: t("terminal.command"), dataIndex: "command", key: "command" },
  { title: t("common.actions"), key: "actions", width: 190 },
]
async function load() {
  if (loading.value) return
  loading.value = true
  error.value = ""
  try {
    const [overview, current] = await Promise.all([
      controlPanelApi.terminal(),
      controlPanelApi.settings(),
    ])
    state.value = overview
    if (!policyDirty.value) {
      settings.value = current
      maxExec.value = current.terminal.max_exec_timeout_seconds
      maxJob.value = current.terminal.max_job_runtime_seconds
      maxProcesses.value = current.terminal.max_concurrent_processes ?? 16
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Unable to load terminal"
  } finally {
    loading.value = false
  }
}
async function savePolicy() {
  if (!settings.value) return
  savingPolicy.value = true
  try {
    settings.value = await controlPanelApi.updateSettings(
      settingsUpdatePayload(settings.value, {
        terminal_max_concurrent_processes: maxProcesses.value,
        terminal_max_exec_timeout_seconds: maxExec.value,
        terminal_max_job_runtime_seconds: maxJob.value,
      }),
    )
    notifications.success(String(t("notifications.saved")))
  } finally {
    savingPolicy.value = false
  }
}
async function inspect(id: string) {
  selected.value = await controlPanelApi.terminalJob(id)
}
async function cancel(id: string) {
  await controlPanelApi.cancelTerminalJob(id)
  notifications.success(String(t("notifications.saved")))
  await load()
  if (selected.value) await inspect(id)
}
async function deleteJob(id: string) {
  if (!await requestConfirmation(t("confirmations.deleteJob", { id }))) return
  await controlPanelApi.deleteTerminalJob(id)
  notifications.success(String(t("notifications.deleted")))
  await load()
}
async function deleteWorkspace(id: string) {
  if (!await requestConfirmation(t("confirmations.deleteWorkspace", { id }))) return
  await controlPanelApi.deleteWorkspace(id)
  notifications.success(String(t("notifications.deleted")), id)
  await load()
}
async function cleanup() {
  if (!await requestConfirmation(String(t("terminal.cleanupConfirm")))) return
  await controlPanelApi.cleanupTerminalJobs(168)
  notifications.success(String(t("notifications.deleted")))
  await load()
}
onMounted(() => { void load(); poll = setInterval(() => { if (pageActivity.isActive()) void load() }, 5000) })
onBeforeUnmount(() => clearInterval(poll))
</script>
<template>
  <div class="space-y-6">
    <PageHeader
      :title="t('nav.terminal')"
      :description="t('terminal.description')"
      ><Button variant="outline" size="sm" @click="load"
        ><RefreshCw class="mr-2 size-4" />{{ t("common.refresh") }}</Button
      ><Button variant="outline" size="sm" @click="cleanup"
        ><Trash2 class="mr-2 size-4" />{{ t("terminal.cleanup") }}</Button
      ></PageHeader
    >
    <p v-if="error" class="text-sm text-destructive">{{ error }}</p>
    <div v-if="state" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        :label="t('terminal.workspaces')"
        :value="workspaces.length"
      /><StatCard :label="t('terminal.jobs')" :value="jobs.length" /><StatCard
        :label="t('terminal.running')"
        :value="running"
      /><StatCard :label="t('terminal.failed')" :value="failed" />
    </div>
    <section
      v-if="state"
      class="rounded-xl border border-border bg-card p-4 text-sm"
    >
      <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <span class="text-muted-foreground">{{ t("terminal.shell") }}</span>
          <div class="font-mono text-xs">
            {{ textValue(state.status.shell) }}
          </div>
        </div>
        <div>
          <span class="text-muted-foreground">{{
            t("terminal.workspaceRoot")
          }}</span>
          <div class="font-mono text-xs">
            {{ textValue(state.status.workspace_root) }}
          </div>
        </div>
        <div>
          <span class="text-muted-foreground">{{
            t("terminal.freeDisk")
          }}</span>
          <div>{{ formatBytes(state.status.disk.free_bytes) }}</div>
        </div>
        <div>
          <span class="text-muted-foreground">{{
            t("terminal.gitConfigured")
          }}</span>
          <div>
            {{ state.status.git_configured ? t("common.yes") : t("common.no") }}
          </div>
        </div>
      </div>
    </section>
    <section v-if="state?.status.resources?.available" class="rounded-xl border border-border bg-card p-4">
      <h2 class="mb-3 text-sm font-semibold">{{ t("terminal.containerResources") }}</h2>
      <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4 text-sm">
        <div><div class="text-muted-foreground">CPU</div>{{ state.status.resources.cpu_cores ?? t("terminal.noLimit") }}</div>
        <div><div class="text-muted-foreground">RAM</div>{{ state.status.resources.memory_bytes ? formatBytes(state.status.resources.memory_bytes) : t("terminal.noLimit") }}</div>
        <div><div class="text-muted-foreground">{{ t("terminal.processes") }}</div>{{ state.status.resources.pids_current ?? '—' }} / {{ state.status.resources.pids_limit ?? t("terminal.noLimit") }}</div>
        <div><div class="text-muted-foreground">{{ t("terminal.zombies") }}</div>{{ state.status.resources.zombie_processes }}</div>
      </div>
      <p class="mt-3 text-xs text-muted-foreground">{{ t("terminal.containerLimitsHint") }}</p>
    </section>
    <LoadingSkeleton v-if="!settings" :rows="4" :columns="2" />
    <section v-else class="settings-card">
      <div class="flex items-center justify-between">
        <div>
          <h2>{{ t("settings.terminal") }}</h2>
          <p class="text-xs text-muted-foreground">
            {{ t("terminal.policyHint") }}
          </p>
        </div>
        <Button size="sm" :disabled="savingPolicy || !settings || !policyDirty" @click="savePolicy"
          ><Save class="mr-2 size-4" />{{ t("common.save") }}</Button
        >
      </div>
      <label class="setting-row"><span><b>{{ t("terminal.maxProcesses") }}</b><small>{{ t("terminal.maxProcessesHint") }}</small></span><InputNumber v-model:value="maxProcesses" :min="1" :max="256" /></label>
      <label class="setting-row"
        ><span
          ><b>{{ t("terminal.maxExec") }}</b
          ><small>{{ t("common.seconds") }}</small></span
        ><InputNumber v-model:value="maxExec" :min="1" :max="86400" /></label
      ><label class="setting-row"
        ><span
          ><b>{{ t("terminal.maxRuntime") }}</b
          ><small>{{ t("common.seconds") }}</small></span
        ><InputNumber v-model:value="maxJob" :min="1" :max="604800"
      /></label>
    </section>
    <div class="space-y-3">
      <h2 class="text-sm font-semibold">{{ t("terminal.workspaces") }}</h2>
      <DataTable
        :columns="workspaceColumns"
        :data-source="workspaces"
        :loading="loading && state === null"
        row-key="workspace_id"
        :pagination="false"
        virtual
        :scroll-y="420"
        ><template #bodyCell="{ column, record, value }"
          ><template v-if="column.key === 'actions'"
            ><Button
              variant="ghost"
              size="sm"
              @click="deleteWorkspace(record.workspace_id)"
              >{{ t("common.delete") }}</Button
            ></template
          ><template v-else
            ><span class="truncate">{{ value ?? "—" }}</span></template
          ></template
        ></DataTable
      >
    </div>
    <div class="space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3"><h2 class="text-sm font-semibold">{{ t("terminal.jobs") }}</h2><Select v-model:value="jobFilter" :aria-label="t('terminal.jobFilter')" class="w-48" :options="[{value:'all',label:t('terminal.allJobs')},{value:'active',label:t('terminal.activeJobs')},{value:'finished',label:t('terminal.finishedJobs')}]" /></div>
      <DataTable
        :columns="jobColumns"
        :data-source="filteredJobs"
        :loading="loading && state === null"
        row-key="job_id"
        :pagination="false"
        virtual
        :scroll-y="520"
        ><template #bodyCell="{ column, record, value }"
          ><template v-if="column.key === 'state'"
            ><Tag
              :color="
                record.state === 'running'
                  ? 'green'
                  : record.state === 'failed'
                    ? 'red'
                    : 'default'
              "
              >{{ record.state }}</Tag
            ></template
          ><template v-else-if="column.key === 'job_id'"
            ><button
              class="font-mono text-xs underline"
              @click="inspect(record.job_id)"
            >
              {{ String(record.job_id).slice(0, 12) }}
            </button></template
          ><template v-else-if="column.key === 'actions'"
            ><div class="flex gap-1">
              <Button
                variant="ghost"
                size="sm"
                @click="inspect(record.job_id)"
                >{{ t("terminal.inspect") }}</Button
              ><Button
                v-if="['running', 'cancelling'].includes(record.state)"
                variant="ghost"
                size="sm"
                @click="cancel(record.job_id)"
                >{{ t("terminal.cancel") }}</Button
              ><Button
                v-else
                variant="ghost"
                size="sm"
                @click="deleteJob(record.job_id)"
                >{{ t("common.delete") }}</Button
              >
            </div></template
          ><template v-else
            ><span class="truncate">{{ value ?? "—" }}</span></template
          ></template
        ></DataTable
      >
    </div>
    <Modal
      :open="Boolean(selected)"
      :title="t('terminal.jobTitle')"
      :footer="null"
      width="900px"
      @cancel="selected = null"
      ><div v-if="selected" class="space-y-4 text-sm">
        <div class="grid gap-3 sm:grid-cols-3">
          <div>
            <span class="text-muted-foreground">{{ t("terminal.state") }}</span>
            <div>{{ textValue(selected.job.state) }}</div>
          </div>
          <div>
            <span class="text-muted-foreground">{{
              t("terminal.workspace")
            }}</span>
            <div>{{ textValue(selected.job.workspace_id) }}</div>
          </div>
          <div>
            <span class="text-muted-foreground">{{
              t("terminal.started")
            }}</span>
            <div>{{ formatDate(selected.job.started_at) }}</div>
          </div>
        </div>
        <pre
          class="max-h-[55vh] overflow-auto rounded-lg bg-black p-4 text-xs text-zinc-200 whitespace-pre-wrap"
          >{{ textValue(selected.tail.output) }}</pre
        >
      </div></Modal
    >
  </div>
</template>
