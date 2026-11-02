<script setup lang="ts">
import { computed } from "vue";
import { Button } from "@/shared/ui/button";
import {DataTable,type DataTableColumn} from "@/shared/ui/data-table";
import RowActions from "@/shared/ui/RowActions.vue";
import type { ManagedProject } from "../model/types";

const props = defineProps<{
  projects: ManagedProject[];
  ownerNames: Record<string, string>;
  disabled: boolean;
  loading?: boolean;
  groupByOwner?: boolean;
  hideOwner?: boolean;
  readOnly?: boolean;
}>();
const emit = defineEmits<{ rename: [project: ManagedProject] }>();
const rows = computed(() =>
  props.projects.map((project) => ({
    ...project,
    ownerName: props.ownerNames[project.owner_team_id || project.owner_user_id || ""] || "—",
  })),
);
const allColumns: DataTableColumn<keyof (typeof rows.value)[number]>[] = [
  { key: "name", title: "Проект", dataIndex: "name" },
  { key: "ownerName", title: "Владелец", dataIndex: "ownerName" },
  { key: "actions", title: "", sortable: false },
];
const columns = computed(() =>
  allColumns.filter(
    (column) =>
      (column.key !== "ownerName" || (!props.hideOwner && !props.groupByOwner)) &&
      (column.key !== "actions" || !props.readOnly),
  ),
);
const groups = computed(() => {
  if (!props.groupByOwner) return [{ id: "all", name: "", rows: rows.value }];
  const grouped = new Map<string, { id: string; name: string; rows: typeof rows.value }>();
  for (const project of rows.value) {
    const id = project.owner_team_id || project.owner_user_id || "unknown";
    const group = grouped.get(id) ?? {
      id,
      name: project.owner_team_id ? project.ownerName : `Личные проекты · ${project.ownerName}`,
      rows: [],
    };
    group.rows.push(project);
    grouped.set(id, group);
  }
  return [...grouped.values()];
});
</script>
<template>
  <div class="space-y-5">
    <section v-for="group in groups" :key="group.id" class="space-y-2">
      <h3 v-if="groupByOwner" class="text-sm font-medium">{{ group.name }}</h3>
      <DataTable :columns="columns" :rows="group.rows" :loading="loading" label="Проекты"
        ><template #cell="{ row, column }"
          ><span v-if="column.key === 'name'" class="font-medium" :title="row.id">{{
            row.name
          }}</span><span v-else-if="column.key === 'ownerName'">{{ row.ownerName }}</span
          ><RowActions v-else :label="`Действия с проектом ${row.name}`" :disabled="disabled"
            ><Button
              size="sm"
              variant="ghost"
              class="w-full justify-start"
              @click="emit('rename', row)"
              >Переименовать</Button
            ></RowActions
          ></template
        ></DataTable
      >
    </section>
    <p v-if="!groups.length" class="py-8 text-center text-sm text-muted-foreground">
      Проектов пока нет
    </p>
  </div>
</template>
