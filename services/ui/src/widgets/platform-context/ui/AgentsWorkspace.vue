<script setup lang="ts">
import type { VerifiedPlatformContext } from "@/entities/workspace";
import {
  type AgentDirectoryPort,
  decodeAgentDirectoryDetail,
  decodeAgentDirectoryPage,
  useAgentDirectory,
} from "@/features/platform";
import { eventBus } from "@/shared/events";
import { DataTable, type DataTableColumn } from "@/shared/ui/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/shared/ui/dialog";
import RelativeTime from "@/shared/ui/RelativeTime.vue";
import StatusBadge from "@/shared/ui/StatusBadge.vue";

const props = defineProps<{ context: VerifiedPlatformContext; projectId: string | null }>();
const directory: AgentDirectoryPort = {
  async list(project, cursor, signal) {
    return eventBus.request(
      "agents.list",
      { project_uuid: project, ...(cursor ? { cursor } : {}), limit: 100 },
      (raw) => decodeAgentDirectoryPage(raw, project, cursor),
      signal,
    );
  },
  async get(project, id, signal) {
    return eventBus.request(
      "agents.get",
      { project_uuid: project, id },
      (raw) => decodeAgentDirectoryDetail(raw, project, id),
      signal,
    );
  },
};
const { rows, selected, loading, error, project, open } = useAgentDirectory(props, directory);
const columns: DataTableColumn<keyof (typeof rows.value)[number]>[] = [
  { key: "name", title: "Агент", dataIndex: "name" },
  { key: "parent", title: "Родительский агент", dataIndex: "parent_agent_id" },
  { key: "state", title: "Состояние", dataIndex: "enabled" },
  { key: "created", title: "Создан", dataIndex: "created_at" },
];
</script>
<template>
  <section class="space-y-4">
    <div>
      <h2 class="text-lg font-semibold">Агенты</h2>
      <p class="text-sm text-muted-foreground">
        {{ project?.name || "Выберите проект в шапке" }} · зарегистрированные идентичности агентов,
        отдельно от сеансов выполнения.
      </p>
    </div>
    <p v-if="error" role="alert" class="text-sm text-destructive">{{ error }}</p>
    <DataTable
      v-if="projectId"
      :rows="rows"
      :columns="columns"
      label="Агенты проекта"
      :loading="loading"
      selectable
      @select="open"
      ><template #cell="{ row, column }"
        ><span v-if="column.key === 'name'" :title="row.id">{{ row.name }}</span
        ><span v-else-if="column.key === 'parent'" :title="row.parent_agent_id || ''">{{
          row.parent_agent_id
            ? rows.find((a) => a.id === row.parent_agent_id)?.name || "Агент недоступен"
            : "—"
        }}</span><StatusBadge
          v-else-if="column.key === 'state'"
          :label="row.enabled ? 'Активен' : 'Отключён'"
          :tone="row.enabled ? 'success' : 'neutral'"
        /><RelativeTime v-else :value="row.created_at" /></template
      ></DataTable
    >
    <p v-if="projectId && !loading && !error && !rows.length" class="text-sm text-muted-foreground">
      В этом проекте агенты ещё не зарегистрированы.
    </p>
    <Dialog
      :open="!!selected"
      @update:open="
        (v) => {
          if (!v) selected = null;
        }
      "
      ><DialogContent
        ><DialogHeader
          ><DialogTitle>{{ selected?.name }}</DialogTitle
          ><DialogDescription
            >Зарегистрированный агент выбранного проекта</DialogDescription
          ></DialogHeader
        >
        <dl v-if="selected" class="space-y-3 text-sm">
          <div>
            <dt class="text-muted-foreground">Идентификатор</dt>
            <dd class="break-all font-mono">{{ selected.id }}</dd>
          </div>
          <div>
            <dt class="text-muted-foreground">Состояние</dt>
            <dd>{{ selected.enabled ? "Активен" : "Отключён" }}</dd>
          </div>
          <div>
            <dt class="text-muted-foreground">Родитель</dt>
            <dd class="break-all">
              {{
                selected.parent_agent_id
                  ? rows.find((a) => a.id === selected?.parent_agent_id)?.name ||
                    selected.parent_agent_id
                  : "Нет"
              }}
            </dd>
          </div>
          <div>
            <dt class="text-muted-foreground">Создан</dt>
            <dd><RelativeTime :value="selected.created_at" /></dd>
          </div>
        </dl></DialogContent
      ></Dialog
    >
  </section>
</template>
